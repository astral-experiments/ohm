# Paired formatter benchmarks

We ran Ohm 1.99.0-8 and 1.99.0-9 on the same Linux host with warmed, private formatter caches. Each case had 40 pairs. Both releases received the same input and produced identical output. We shuffled the order so each release ran first in 20 pairs.

| Project | Formatting case                |  -8 median |  -9 median |  -9 / -8 time (99% CI) |
| ------- | ------------------------------ | ---------: | ---------: | ---------------------: |
| ruff    | Unchanged file                 |  120.15 ms |  119.92 ms | 0.9700 (0.8559–1.1100) |
| ruff    | Already formatted comment      |  170.47 ms |  178.54 ms | 1.1498 (1.0193–1.3312) |
| ruff    | Whitespace requiring a rewrite |  240.03 ms |  242.70 ms | 1.0794 (0.9677–1.2082) |
| uv      | Unchanged file                 |   97.66 ms |  154.72 ms | 1.2168 (0.9809–1.4967) |
| uv      | Already formatted comment      |  846.54 ms |  920.12 ms | 1.0952 (1.0455–1.1466) |
| uv      | Whitespace requiring a rewrite | 1499.03 ms | 1559.53 ms | 1.0563 (1.0221–1.0906) |

The median columns summarize each release separately. For the last column, we divided the -9 time by the -8 time within each pair and took the geometric mean of the 40 ratios. A ratio below 1 favors -9. The 99% confidence intervals use 20,000 bootstrap resamples of the pairs.

Both releases ran `cargo +<release> fmt -p <package>` with their published defaults. We edited `doc_lines.rs` in `ruff_linter` at Ruff revision `4d6a7db787130c5a4a95bd835369babd78e4a1f6` and `install_source.rs` in `uv` at revision `c22e6b71933443e9cd299d4b6ac8de035ed4825b`.

The data includes the execution order and elapsed time for every pair. Its reproduction record contains the edit fixtures, randomization seeds, and exact runner inputs. [Paired measurements and protocol](formatting-comparison.json)
