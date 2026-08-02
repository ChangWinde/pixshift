"""Operation wrappers for dedup workflows."""

from ..dedup_engine import DedupResult, DeleteCandidate, delete_duplicates, find_duplicates


def analyze(
    input_paths: list[str], recursive: bool, hash_method: str, threshold: int
) -> DedupResult:
    """Find duplicate groups for input paths."""
    return find_duplicates(
        input_paths=input_paths,
        recursive=recursive,
        hash_method=hash_method,
        threshold=threshold,
    )


def delete(groups: list[DeleteCandidate], dry_run: bool = False) -> dict[str, list[str]]:
    """Delete duplicate files for selected groups."""
    return delete_duplicates(groups, dry_run=dry_run)
