# Paired formatter benchmarks

We ran Ohm 1.99.0-7 and 1.99.0-8 on the same Linux host with warmed, private formatter caches. Each case had 40 pairs. Both releases formatted the same input in each pair and produced identical output. We shuffled the order so that each release ran first in 20 pairs.

| Project | Formatting case                |  -7 median |  -8 median |  -8 / -7 time (99% CI) |
| ------- | ------------------------------ | ---------: | ---------: | ---------------------: |
| ruff    | Unchanged file                 |  109.18 ms |  107.11 ms | 0.9966 (0.9815–1.0153) |
| ruff    | Already formatted comment      |  174.96 ms |  170.76 ms | 0.9743 (0.9652–0.9838) |
| ruff    | Whitespace requiring a rewrite | 4528.86 ms |  231.25 ms | 0.0510 (0.0507–0.0514) |
| uv      | Unchanged file                 |   82.31 ms |   81.46 ms | 0.9936 (0.9815–1.0061) |
| uv      | Already formatted comment      |  830.15 ms |  715.38 ms | 0.8570 (0.8490–0.8639) |
| uv      | Whitespace requiring a rewrite | 1583.62 ms | 1347.34 ms | 0.8509 (0.8478–0.8542) |

The median columns summarize each release separately. For the last column, we divided the -8 time by the -7 time within each pair and took the geometric mean of the 40 ratios. Ratios below 1 favor -8. The 99% confidence intervals use 20,000 bootstrap resamples of the pairs.

Both releases ran `cargo +<release> fmt -p <package>` with their published defaults. We edited `doc_lines.rs` in `ruff_linter` at Ruff revision `4d6a7db787130c5a4a95bd835369babd78e4a1f6` and `install_source.rs` in `uv` at revision `c22e6b71933443e9cd299d4b6ac8de035ed4825b`.
