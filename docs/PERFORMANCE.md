# Performance Notes

PixShift optimizes measured hot paths while keeping correctness checks in the
benchmark. Run the duplicate-clustering benchmark from the repository root:

```bash
uv run python benchmarks/dedup_index.py --items 4000 --threshold 5
```

Reference result on the repair environment (Python 3.13, 4,000 deterministic
64-bit hashes, threshold 5):

```text
multi_index=0.0106s brute_force=0.3163s speedup=29.8x
```

Absolute timings depend on hardware. The script first verifies that indexed and
exhaustive clustering produce identical connected components; a mismatch fails
the benchmark instead of reporting a misleading speedup.

Other bounded-performance decisions:

- one conversion stays in-process;
- automatic batch conversion uses at most eight worker processes;
- exact duplicate SHA-256 runs only within equal-size buckets;
- encoders atomically publish the exact payload already tested for a target size.
