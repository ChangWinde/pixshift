"""Documentation governance: keep the docs provably in sync with the code.

Documentation rots silently — a flag is renamed, a command is added, a gate is
raised, and the prose keeps claiming the old truth. These tests turn every
machine-checkable documentation fact into a CI failure instead of a surprise
for the reader.

Prose quality is out of scope here; only verifiable claims are asserted.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 CI
    import tomli as tomllib

from pixshift.core.tool_catalog import TOOL_CATALOG

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
MKDOCS = REPO / "mkdocs.yml"

# The user manual: every page the site actually serves.
MANUAL_PAGES = (
    "index.md",
    "install.md",
    "images.md",
    "pdf.md",
    "video.md",
    "automation.md",
    "JSON_OUTPUT.md",
    "faq.md",
)
ROOT_MARKDOWN = {"AGENTS.md", "CHANGELOG.md", "README.md"}
ROOT_FILES = {
    ".gitignore",
    ".pre-commit-config.yaml",
    "AGENTS.md",
    "CHANGELOG.md",
    "LICENSE",
    "MANIFEST.in",
    "README.md",
    "mkdocs.yml",
    "pyproject.toml",
    "uv.lock",
}
ROOT_DIRECTORIES = {".github", "docs", "examples", "pixshift", "scripts", "tests"}
PROJECT_PAGES = {
    "architecture.md",
    "documentation-governance.md",
    "goals.md",
    "labels.md",
    "performance.md",
    "releasing.md",
    "repository-governance.md",
}
HEADING_EXEMPT = {Path(".github/PULL_REQUEST_TEMPLATE.md")}
TEST_SUITES = {"automation", "cli", "core", "image", "integration", "pdf", "repository", "video"}


def _read(relative: str) -> str:
    return (REPO / relative).read_text(encoding="utf-8")


def _repository_paths() -> list[str]:
    if not (REPO / ".git").exists():
        pytest.skip("repository layout governance requires a Git checkout")
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return [path for path in result.stdout.splitlines() if (REPO / path).exists()]


def _manual_text() -> str:
    return "\n".join((DOCS / page).read_text(encoding="utf-8") for page in MANUAL_PAGES)


def _markdown_files() -> list[Path]:
    """Every maintained Markdown surface, excluding generated/installed trees."""
    files = list(REPO.glob("*.md"))
    for directory in (REPO / ".github", DOCS, REPO / "examples", REPO / "tests"):
        files.extend(directory.rglob("*.md"))
    return sorted(set(files))


def _prose_without_fenced_code(text: str) -> str:
    """Remove fenced examples so shell comments are not mistaken for headings."""
    prose: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        stripped = line.lstrip()
        marker = None
        if stripped.startswith("```"):
            marker = "```"
        elif stripped.startswith("~~~"):
            marker = "~~~"
        if marker:
            fence = None if fence == marker else marker
            continue
        if fence is None:
            prose.append(line)
    return "\n".join(prose)


def _mkdocs_config() -> dict:
    # mkdocs.yml uses plain YAML here (no custom tags), so a safe load is enough.
    return yaml.safe_load(MKDOCS.read_text(encoding="utf-8"))


def _nav_files(node, found: list[str]) -> list[str]:
    if isinstance(node, str):
        found.append(node)
    elif isinstance(node, list):
        for item in node:
            _nav_files(item, found)
    elif isinstance(node, dict):
        for value in node.values():
            _nav_files(value, found)
    return found


# ------------------------------------------------------------------
# The manual describes the CLI that actually exists
# ------------------------------------------------------------------


def _documented_invocations(text: str) -> set[str]:
    """Command paths written as `pixshift <group> <sub>` in the manual."""
    groups = {"pdf", "video", "watermark"}
    found: set[str] = set()
    for match in re.finditer(r"pixshift ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?", text):
        first, second = match.group(1), match.group(2)
        if first in groups and second:
            found.add(f"{first}.{second}")
        else:
            found.add(first)
    return found


def _catalog_names() -> set[str]:
    return {str(entry["name"]) for entry in TOOL_CATALOG}


def _cli_command_names() -> set[str]:
    from pixshift.cli import cli

    names: set[str] = set()
    for name, command in cli.commands.items():
        subcommands = getattr(command, "commands", None)
        if subcommands:
            names.update(f"{name}.{sub}" for sub in subcommands)
        else:
            names.add(name)
    return names


def test_manual_documents_every_catalog_command():
    """A new command must not ship without a line in the manual."""
    documented = _documented_invocations(_manual_text())
    # watermark is catalogued once but documented as two subcommands.
    documented |= {"watermark"} if {"watermark.text", "watermark.image"} & documented else set()
    missing = sorted(_catalog_names() - documented)
    assert not missing, f"tool catalog entries absent from the manual: {missing}"


def test_manual_never_invents_a_command():
    """Every `pixshift ...` invocation in the manual must resolve."""
    real = _cli_command_names() | {name.split(".")[0] for name in _cli_command_names()}
    # Non-command words that legitimately follow "pixshift" in prose/URLs.
    allowed = real | {"tools", "doctor", "formats"}
    unknown = sorted(
        name for name in _documented_invocations(_manual_text()) if name not in allowed
    )
    assert not unknown, f"manual references commands that do not exist: {unknown}"


# ------------------------------------------------------------------
# Numbers and identifiers stated in prose match the code and CI
# ------------------------------------------------------------------


def test_coverage_gate_is_stated_consistently():
    ci_gates = set(re.findall(r"--cov-fail-under=(\d+)", _read(".github/workflows/ci.yml")))
    assert len(ci_gates) == 1, f"CI declares conflicting coverage gates: {ci_gates}"
    gate = ci_gates.pop()
    for path in (
        ".github/CONTRIBUTING.md",
        "docs/project/releasing.md",
        ".github/workflows/release.yml",
    ):
        stated = set(re.findall(r"--cov-fail-under=(\d+)", _read(path)))
        assert stated <= {gate}, f"{path} states coverage gate {stated}, CI enforces {gate}"
    policy = re.search(r"repository-wide gate is `(\d+)%`", _read("docs/project/releasing.md"))
    assert policy and policy.group(1) == gate, "RELEASING coverage policy disagrees with CI"


def test_schema_version_is_stated_consistently():
    from pixshift.presenters.json_presenters import emit_json  # noqa: F401

    source = _read("pixshift/presenters/json_presenters.py")
    actual = re.search(r'"schema_version": "([\d.]+)"', source)
    assert actual, "cannot locate schema_version in the JSON presenter"
    version = actual.group(1)

    contract = _read("docs/JSON_OUTPUT.md")
    assert f'`"{version}"`' in contract, f"JSON_OUTPUT.md does not state schema {version}"
    assert f"schema_version {version}" in _read("docs/project/architecture.md")
    assert f'"schema_version": "{version}"' in _read("README.md")

    for schema_file in sorted((DOCS / "schemas" / "v1").glob("*.json")):
        text = schema_file.read_text(encoding="utf-8")
        if "schema_version" in text:
            assert f'"const": "{version}"' in text, f"{schema_file.name} pins another version"


def test_documented_exit_codes_match_the_implementation():
    from pixshift.commands.common import usage_error_or_exit  # noqa: F401

    source = _read("pixshift/commands/common.py")
    assert "``2`` usage rejection" in source or "exit 2" in source
    for doc in ("docs/JSON_OUTPUT.md", "docs/automation.md"):
        text = _read(doc)
        assert "`2`" in text and "`1`" in text and "`0`" in text, f"{doc} omits an exit code"


def test_standard_install_declares_and_packages_every_media_runtime() -> None:
    project_file = tomllib.loads(_read("pyproject.toml"))
    project = project_file["project"]
    requirements = {item.split(";", 1)[0].strip().lower() for item in project["dependencies"]}

    assert any(item.startswith("pillow-avif-plugin") for item in requirements)
    assert not any(item.startswith("ffmpeg-binaries") for item in requirements)
    package_data = project_file["tool"]["setuptools"]["package-data"]["pixshift"]
    assert "_runtime/bin/*" in package_data
    assert (REPO / "scripts" / "media_runtime_manifest.json").is_file()


# ------------------------------------------------------------------
# Structure: nothing orphaned, nothing dangling
# ------------------------------------------------------------------


def test_documentation_has_one_deliberate_home_per_audience():
    """The root and public docs root remain curated discovery surfaces."""
    root_markdown = {path.name for path in REPO.glob("*.md")}
    assert root_markdown == ROOT_MARKDOWN, (
        "root Markdown is reserved for README, changelog, and agent discovery; "
        "put community policy in .github/ or engineering references in docs/project/"
    )

    public_root = {path.name for path in DOCS.glob("*.md")}
    assert public_root == set(MANUAL_PAGES), (
        "docs/*.md is the published manual; put maintainer references in docs/project/"
    )

    project_pages = {path.name for path in (DOCS / "project").glob("*.md")}
    assert project_pages == PROJECT_PAGES, (
        "update PROJECT_PAGES and documentation-governance.md when adding a project reference"
    )


def test_tracked_repository_root_is_a_curated_compatibility_surface():
    paths = _repository_paths()
    root_files = {path for path in paths if "/" not in path}
    root_directories = {path.split("/", 1)[0] for path in paths if "/" in path}
    assert root_files == ROOT_FILES, "update ADR-0007 before changing the root-file contract"
    assert root_directories == ROOT_DIRECTORIES, (
        "group new material under an owned root directory or supersede ADR-0007"
    )


def test_test_modules_are_grouped_by_owned_boundary():
    suites = {
        path.name
        for path in (REPO / "tests").iterdir()
        if path.is_dir() and not path.name.startswith((".", "__"))
    }
    assert suites == TEST_SUITES
    loose_modules = sorted(path.name for path in (REPO / "tests").glob("test_*.py"))
    assert not loose_modules, f"place test modules in an owned suite: {loose_modules}"


def test_every_document_has_one_top_level_heading():
    malformed: list[str] = []
    for markdown in _markdown_files():
        if markdown.relative_to(REPO) in HEADING_EXEMPT:
            continue
        prose = _prose_without_fenced_code(markdown.read_text(encoding="utf-8"))
        headings = re.findall(r"^# [^#].+$", prose, flags=re.MULTILINE)
        if len(headings) != 1:
            malformed.append(f"{markdown.relative_to(REPO)} ({len(headings)} H1 headings)")
    assert not malformed, f"documents must have exactly one H1: {malformed}"


def test_repository_metadata_points_to_the_published_manual():
    site_url = str(_mkdocs_config()["site_url"])
    metadata = re.search(
        r'^Documentation = "([^"]+)"$', _read("pyproject.toml"), flags=re.MULTILINE
    )
    assert metadata and metadata.group(1) == site_url
    assert site_url in _read("README.md")


def test_strict_build_and_deployment_sources_are_policy():
    config = _mkdocs_config()
    assert config.get("strict") is True, "mkdocs.yml must default to strict validation"
    workflow = _read(".github/workflows/docs.yml")
    for source in ("docs/**", "mkdocs.yml", ".github/workflows/docs.yml"):
        assert source in workflow, f"Docs workflow does not watch {source}"
    assert "mkdocs build --strict" in workflow
    assert "actions/upload-pages-artifact@" in workflow
    assert "actions/deploy-pages@" in workflow
    assert "mkdocs gh-deploy" not in workflow


def test_workflows_use_read_only_checkout_credentials() -> None:
    for workflow_path in sorted((REPO / ".github" / "workflows").glob("*.yml")):
        workflow = workflow_path.read_text(encoding="utf-8")
        checkout_count = workflow.count("uses: actions/checkout@")
        if checkout_count:
            assert workflow.count("persist-credentials: false") == checkout_count, (
                f"{workflow_path.name} must disable checkout credentials in every job"
            )


def test_hosted_security_and_release_controls_are_versioned() -> None:
    ci_workflow = _read(".github/workflows/ci.yml")
    assert "${{ github.base_ref }}" not in re.findall(r"run:.*", ci_workflow)

    codeql = _read(".github/workflows/codeql.yml")
    assert "github/codeql-action/init@" in codeql
    assert "github/codeql-action/analyze@" in codeql
    assert "security-events: write" in codeql

    release = _read(".github/workflows/release.yml")
    for contract in (
        'git cat-file -t "refs/tags/${GITHUB_REF_NAME}"',
        "sha256sum dist/*.whl dist/*.tar.gz",
        "anchore/sbom-action@",
        "actions/attest@",
        "sbom-path: release-sbom.spdx.json",
        "gh release create",
    ):
        assert contract in release, f"release workflow omits integrity contract: {contract}"

    adr = _read("docs/adr/0009-repository-and-release-integrity.md")
    assert "`MANIFEST.in` is added to the curated root contract" in adr


def test_documentation_has_an_explicit_review_owner():
    owners = _read(".github/CODEOWNERS")
    for path in ("/README.md", "/AGENTS.md", "/mkdocs.yml", "/docs/", "/.github/"):
        assert re.search(rf"^{re.escape(path)}\s+@\S+", owners, flags=re.MULTILINE), (
            f"CODEOWNERS does not route review for {path}"
        )


def test_every_docs_page_is_either_published_or_explicitly_excluded():
    config = _mkdocs_config()
    published = {Path(item).as_posix() for item in _nav_files(config["nav"], [])}
    excluded = [line.strip() for line in config["exclude_docs"].splitlines() if line.strip()]

    for page in sorted(DOCS.rglob("*.md")):
        relative = page.relative_to(DOCS).as_posix()
        if relative in published:
            continue
        if any(relative == rule or relative.startswith(rule) for rule in excluded):
            continue
        pytest.fail(
            f"docs/{relative} is neither in the site nav nor in mkdocs exclude_docs; "
            "decide whether it is user documentation or an engineering reference"
        )


def test_nav_entries_exist():
    for entry in _nav_files(_mkdocs_config()["nav"], []):
        assert (DOCS / entry).is_file(), f"mkdocs nav points at a missing file: {entry}"


def test_manual_pages_match_the_nav():
    published = {Path(item).as_posix() for item in _nav_files(_mkdocs_config()["nav"], [])}
    assert published == set(MANUAL_PAGES), (
        "MANUAL_PAGES in this test drifted from the site nav; update both deliberately"
    )


def test_relative_markdown_links_resolve():
    broken: list[str] = []
    pattern = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
    for markdown in _markdown_files():
        text = markdown.read_text(encoding="utf-8")
        for raw_target in pattern.findall(text):
            target = raw_target.split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            if not (markdown.parent / target).resolve().exists():
                broken.append(f"{markdown.relative_to(REPO)} -> {target}")
    assert not broken, f"broken relative documentation links: {broken}"


def test_canonical_github_links_point_to_checked_in_paths():
    """README links must remain valid when its long description renders on PyPI."""
    prefix = (
        r"https://(?:github\.com/ChangWinde/pixshift/(?:blob|tree)/main/|"
        r"raw\.githubusercontent\.com/ChangWinde/pixshift/main/)"
    )
    pattern = re.compile(prefix + r'([^\s)"#]+)')
    missing: list[str] = []
    for markdown in _markdown_files():
        for target in pattern.findall(markdown.read_text(encoding="utf-8")):
            if not (REPO / target).exists():
                missing.append(f"{markdown.relative_to(REPO)} -> {target}")
    assert not missing, f"canonical GitHub links point to missing paths: {missing}"


def test_referenced_repository_paths_exist():
    """Backtick-quoted repo paths in the docs must point at real files."""
    pattern = re.compile(r"`((?:docs|scripts|examples|tests|pixshift|\.github)/[\w./-]+)`")
    missing: list[str] = []
    for markdown in _markdown_files():
        for target in pattern.findall(markdown.read_text(encoding="utf-8")):
            path = REPO / target
            if not path.exists():
                missing.append(f"{markdown.relative_to(REPO)} -> {target}")
    assert not missing, f"documentation references missing repository paths: {missing}"
