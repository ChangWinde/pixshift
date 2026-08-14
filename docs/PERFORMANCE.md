# Performance Notes

PixShift optimizes measured hot paths while keeping correctness checks in the
benchmark. Run the duplicate-clustering benchmark from the repository root:

```bash
uv run python scripts/dedup_index_bench.py --items 4000 --threshold 5
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
- optimization analysis trial-encodes at most a 1600 px sample and reports the
  sampling scale in JSON. A 4000×3000 benchmark improved from 7.055s to 1.542s
  (4.6×) while retaining original dimensions in the result.
- montage performs a lightweight dimension pass and then decodes one image at a
  time. A 24-image 2000×1500 benchmark reduced peak RSS from about 450 MB to
  191 MB (58%) with comparable runtime.
- `pdf merge` splices eligible single-scan JPEG bytes (metadata segments
  dropped, entropy data untouched) instead of decoding and re-encoding when no
  transform is needed. A 12-image 3000×2000 q88 benchmark: 0.87s → 0.20s
  (4.3×) with a 21% smaller PDF and zero generation loss; oriented, CMYK,
  progressive/multi-scan, tailed, alpha, or explicitly recompressed
  (`--quality < 95`) inputs keep the safe re-encode path.
- `pdf compress` resolves image placement rects once per page via
  `get_image_info` instead of one `get_image_rects` content-stream parse per
  image (quadratic on dense pages). Measured on 4 pages × 40 placements:
  0.45s → 0.26s with 8 unique images, 0.61s → 0.23s (2.7×) with 40 unique
  images per page; the win grows with image density.
- The same-format batch surfaces (`compress`, `strip`, `resize`, `rotate`,
  `crop`, `watermark`) run on the shared bounded worker pool (≤8 processes,
  serial below 4 tasks). Measured on 120 photos of 1200×900: compress
  2.39s → 0.53s (4.5×), strip 3.02s → 0.69s (4.4×), resize 2.55s → 0.63s
  (4.0×). Results and failure lists keep task order, so JSON output is
  unchanged.
