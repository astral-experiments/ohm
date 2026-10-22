Published Ohm 1.99.0-8 versus 1.99.0-7, using 40 paired measurements per case on the same Linux host. Both releases produced identical formatted output. Each pair used the same input; execution order was balanced and shuffled before timing.

| Project | Formatting case                |  -7 median |  -8 median | -8 / -7 time (99% CI) |
| ------- | ------------------------------ | ---------: | ---------: | --------------------: |
| ruff    | Unchanged file                 |  109.18 ms |  107.11 ms |   0.997 (0.981–1.015) |
| ruff    | Already formatted comment      |  174.96 ms |  170.76 ms |   0.974 (0.965–0.984) |
| ruff    | Whitespace requiring a rewrite | 4528.86 ms |  231.25 ms |   0.051 (0.051–0.051) |
| uv      | Unchanged file                 |   82.31 ms |   81.46 ms |   0.994 (0.982–1.006) |
| uv      | Already formatted comment      |  830.15 ms |  715.38 ms |   0.857 (0.849–0.864) |
| uv      | Whitespace requiring a rewrite | 1583.62 ms | 1347.34 ms |   0.851 (0.848–0.854) |

Ratios below 1 favor -8. Confidence intervals use the preregistered paired bootstrap with 20,000 resamples. These results compare the complete published builds and their build inputs; they do not assign gains to individual PRs or measure check/build/test performance.

Sources: Ruff `4d6a7db787130c5a4a95bd835369babd78e4a1f6` (`ruff_linter`, `doc_lines.rs`) and uv `c22e6b71933443e9cd299d4b6ac8de035ed4825b` (`uv`, `install_source.rs`). Both ran `cargo +<release> fmt -p <package>` with published defaults and private formatter caches.
