"""Bounded parallel execution for per-file batch work."""

from __future__ import annotations

import multiprocessing
import os
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any

# Image decoders are memory-heavy; an unbounded CPU-count pool can make large
# batches slower through memory pressure. Same bound the convert path uses.
MAX_BATCH_WORKERS = 8
# Below this task count process startup costs more than it saves.
MIN_PARALLEL_TASKS = 4
DEFAULT_BATCH_MEMORY_MB = 1024
_ESTIMATED_BYTES_PER_PIXEL = 16


def bounded_worker_count(tasks: Sequence[tuple[str, str]], requested: int = 0) -> int:
    """Choose a CPU- and decoded-memory-bounded image worker count.

    Header reads are capped at 64 representative tasks. A corrupt sample does
    not hide later large images; if every sample is unknown, use one worker as
    the conservative memory-safe fallback.
    """
    if not tasks:
        return 0
    cpu_bound = min(multiprocessing.cpu_count(), len(tasks), MAX_BATCH_WORKERS)
    if requested > 0:
        cpu_bound = min(cpu_bound, requested)
    try:
        memory_mb = int(os.environ.get("PIXSHIFT_BATCH_MEMORY_MB", DEFAULT_BATCH_MEMORY_MB))
    except ValueError:
        memory_mb = DEFAULT_BATCH_MEMORY_MB
    memory_bytes = max(64, memory_mb) * 1024 * 1024
    max_pixels = 0
    from .metadata import open_image

    known_samples = 0
    for source, _ in tasks[:64]:
        try:
            with open_image(source) as image:
                max_pixels = max(max_pixels, int(image.width) * int(image.height))
                known_samples += 1
        except Exception:
            continue
    if not known_samples:
        return 1
    memory_bound = max(1, memory_bytes // (max_pixels * _ESTIMATED_BYTES_PER_PIXEL))
    cpu_bound = min(cpu_bound, memory_bound)
    return max(1, cpu_bound)


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
    jobs = bounded_worker_count(tasks)
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
