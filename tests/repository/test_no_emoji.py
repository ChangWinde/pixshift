"""Repository-wide policy tests for concise, professional text."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = {
    ".cfg",
    ".html",
    ".ini",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
ROOT_TEXT_FILES = {"LICENSE", "Makefile"}
IGNORED_PARTS = {
    ".git",
    ".hypothesis",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
    "pixshift.egg-info",
    "site",
}
EMOJI_RANGES = (
    (0x203C, 0x203C),
    (0x2049, 0x2049),
    (0x2139, 0x2139),
    (0x2194, 0x2199),
    (0x21A9, 0x21AA),
    (0x1F000, 0x1FAFF),
    (0x2300, 0x23FF),
    (0x25AA, 0x25AB),
    (0x25B6, 0x25B6),
    (0x25C0, 0x25C0),
    (0x25FB, 0x25FE),
    (0x2600, 0x27BF),
    (0x2934, 0x2935),
    (0x2B00, 0x2BFF),
    (0x3030, 0x3030),
    (0x303D, 0x303D),
    (0x3297, 0x3297),
    (0x3299, 0x3299),
)
EMOJI_COMPONENTS = {0x200D, 0x20E3, 0xFE0F}


def _is_emoji(character: str) -> bool:
    codepoint = ord(character)
    return codepoint in EMOJI_COMPONENTS or any(
        start <= codepoint <= end for start, end in EMOJI_RANGES
    )


def _repository_text_files() -> list[Path]:
    return sorted(
        path
        for path in PROJECT_ROOT.rglob("*")
        if path.is_file()
        and not any(part in IGNORED_PARTS for part in path.parts)
        and (path.suffix.lower() in TEXT_SUFFIXES or path.name in ROOT_TEXT_FILES)
    )


def test_repository_text_contains_no_emoji() -> None:
    violations: list[str] = []
    for path in _repository_text_files():
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            found = "".join(character for character in line if _is_emoji(character))
            if found:
                relative_path = path.relative_to(PROJECT_ROOT)
                violations.append(f"{relative_path}:{line_number}: {found}")

    assert not violations, "Emoji found in repository text:\n" + "\n".join(violations[:50])
