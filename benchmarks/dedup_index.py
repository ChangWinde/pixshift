"""Reproducible perceptual-hash clustering microbenchmark."""

import argparse
import random
import time

from pixshift.dedup_engine import _cluster_by_hash

HashItem = tuple[str, int, int]


def brute_force(items: list[HashItem], threshold: int) -> list[set[str]]:
    """Cluster by exhaustive comparison for a correctness/performance baseline."""
    parents = list(range(len(items)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for left in range(len(items)):
        for right in range(left):
            if (items[left][1] ^ items[right][1]).bit_count() <= threshold:
                left_root = find(left)
                right_root = find(right)
                if left_root != right_root:
                    parents[right_root] = left_root

    groups: dict[int, set[str]] = {}
    for index, item in enumerate(items):
        groups.setdefault(find(index), set()).add(item[0])
    return list(groups.values())


def main() -> None:
    """Run the indexed and exhaustive implementations on identical hashes."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", type=int, default=4000)
    parser.add_argument("--threshold", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260801)
    args = parser.parse_args()

    randomizer = random.Random(args.seed)
    items = [(str(index), randomizer.getrandbits(64), index) for index in range(args.items)]

    started = time.perf_counter()
    indexed = _cluster_by_hash(items, args.threshold)
    indexed_seconds = time.perf_counter() - started

    started = time.perf_counter()
    exhaustive = brute_force(items, args.threshold)
    exhaustive_seconds = time.perf_counter() - started

    indexed_groups = {frozenset(item[0] for item in group) for group in indexed}
    exhaustive_groups = {frozenset(group) for group in exhaustive}
    if indexed_groups != exhaustive_groups:
        raise RuntimeError("indexed clustering disagrees with exhaustive baseline")

    speedup = exhaustive_seconds / indexed_seconds
    print(
        f"items={args.items} threshold={args.threshold} "
        f"multi_index={indexed_seconds:.4f}s brute_force={exhaustive_seconds:.4f}s "
        f"speedup={speedup:.1f}x"
    )


if __name__ == "__main__":
    main()
