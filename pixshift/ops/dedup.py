"""Operation wrappers for dedup workflows."""

from typing import Dict, List

from ..dedup_engine import delete_duplicates, find_duplicates


def analyze(input_paths: List[str], recursive: bool, hash_method: str, threshold: int):
    """Find duplicate groups for input paths."""
    return find_duplicates(
        input_paths=input_paths,
        recursive=recursive,
        hash_method=hash_method,
        threshold=threshold,
    )


def delete(groups: List, dry_run: bool = False) -> Dict:
    """Delete duplicate files for selected groups."""
    return delete_duplicates(groups, dry_run=dry_run)

