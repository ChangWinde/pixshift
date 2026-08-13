"""Bounded parallel execution for per-file batch work."""

from __future__ import annotations

import multiprocessing
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any

# Image decoders are memory-heavy; an unbounded CPU-count pool can make large
# batches slower through memory pressure. Same bound the convert path uses.
MAX_BATCH_WORKERS = 8
# Below this task count process startup costs more than it saves.
MIN_PARALLEL_TASKS = 4


def run_batch_tasks(
    tasks: Sequence[tuple[str, str]],
    worker: Callable[[str, str], Any],
    *,
    on_result: Callable[[], None] | None = None,
) -> list[Any]:
    """Run ``worker(input, output)`` over a batch, in parallel when it pays.

    Results preserve task order regardless of completion order, so JSON
    payloads and failure lists stay deterministic. ``worker`` must be
    picklable (a module-level function or ``functools.partial`` over one).
    ``on_result`` fires once per completed item, for progress ticks.
    """
    if not tasks:
        return []
    jobs = max(1, min(multiprocessing.cpu_count(), len(tasks), MAX_BATCH_WORKERS))
    if jobs <= 1 or len(tasks) < MIN_PARALLEL_TASKS:
        results = []
        for input_path, output_path in tasks:
            results.append(worker(input_path, output_path))
            if on_result is not None:
                on_result()
        return results
    ordered: list[Any] = [None] * len(tasks)
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        futures = {
            pool.submit(worker, input_path, output_path): index
            for index, (input_path, output_path) in enumerate(tasks)
        }
        for future in as_completed(futures):
            ordered[futures[future]] = future.result()
            if on_result is not None:
                on_result()
    return ordered
