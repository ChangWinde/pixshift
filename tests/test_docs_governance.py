"""Documentation governance: keep the docs provably in sync with the code.

Documentation rots silently — a flag is renamed, a command is added, a gate is
raised, and the prose keeps claiming the old truth. These tests turn every
machine-checkable documentation fact into a CI failure instead of a surprise
for the reader.

Prose quality is out of scope here; only verifiable claims are asserted.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from pixshift.core.tool_catalog import TOOL_CATALOG

REPO = Path(__file__).resolve().parent.parent
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


def _read(relative: str) -> str:
    return (REPO / relative).read_text(encoding="utf-8")


def _manual_text() -> str:
    return "\n".join((DOCS / page).read_text(encoding="utf-8") for page in MANUAL_PAGES)


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
    for path in ("CONTRIBUTING.md", "docs/RELEASING.md", ".github/workflows/release.yml"):
        stated = set(re.findall(r"--cov-fail-under=(\d+)", _read(path)))
        assert stated <= {gate}, f"{path} states coverage gate {stated}, CI enforces {gate}"
    policy = re.search(r"repository-wide gate is `(\d+)%`", _read("docs/RELEASING.md"))
    assert policy and policy.group(1) == gate, "RELEASING coverage policy disagrees with CI"


def test_schema_version_is_stated_consistently():
    from pixshift.presenters.json_presenters import emit_json  # noqa: F401

    source = _read("pixshift/presenters/json_presenters.py")
    actual = re.search(r'"schema_version": "([\d.]+)"', source)
    assert actual, "cannot locate schema_version in the JSON presenter"
    version = actual.group(1)

    contract = _read("docs/JSON_OUTPUT.md")
    assert f'`"{version}"`' in contract, f"JSON_OUTPUT.md does not state schema {version}"
    assert f"schema_version {version}" in _read("docs/ARCHITECTURE.md")

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


# ------------------------------------------------------------------
# Structure: nothing orphaned, nothing dangling
# ------------------------------------------------------------------


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
    for markdown in sorted(REPO.glob("*.md")) + sorted(DOCS.rglob("*.md")):
        text = markdown.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)]+\.md)(?:#[^)]*)?\)", text):
            if target.startswith(("http://", "https://")):
                continue
            if not (markdown.parent / target).resolve().is_file():
                broken.append(f"{markdown.relative_to(REPO)} -> {target}")
    assert not broken, f"broken relative documentation links: {broken}"


def test_referenced_repository_paths_exist():
    """Backtick-quoted repo paths in the docs must point at real files."""
    pattern = re.compile(r"`((?:docs|scripts|examples|tests|pixshift|\.github)/[\w./-]+)`")
    missing: list[str] = []
    for markdown in sorted(REPO.glob("*.md")) + sorted(DOCS.rglob("*.md")):
        for target in pattern.findall(markdown.read_text(encoding="utf-8")):
            path = REPO / target
            if not path.exists() and not path.parent.exists():
                missing.append(f"{markdown.relative_to(REPO)} -> {target}")
    assert not missing, f"documentation references missing repository paths: {missing}"
