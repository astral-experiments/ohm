# Production compile after uv #21041

Eight matched pairs measured `cargo check -p uv-client --locked --offline -j8` after applying the landed uv edit to four independently warmed parent caches, two per compiler. Both compilers used the same Ohm −22 PGO+BOLT build recipe, signed −22 Cargo, and the same fix for incremental constant allocations. The control was `4cc83ad906d8` with #296 and #306. The candidate, its direct child `f53496e2dd36`, adds recovery of typed callable receivers during incremental trait selection. [Real uv edit](https://github.com/astral-sh/uv/pull/21041) · [Physical run](https://github.com/astral-experiments/ohm/actions/runs/41404703005)

| Endpoint | Control | Candidate | Paired factor | Reduction | First four | Last four |
|---|---:|---:|---:|---:|---:|---:|
| Whole command, seconds | 1.466 | 1.291 | 1.107× | 9.70% | 1.099× | 1.124× |
| Whole command, instructions (billions) | 11.054 | 9.882 | 1.119× | 10.61% | 1.119× | 1.118× |
| All eight rustc processes, instructions (billions) | 10.464 | 9.292 | 1.126× | 11.20% | 1.126× | 1.126× |
| Terminal uv_client rustc, instructions (billions) | 3.564 | 3.103 | 1.148× | 12.92% | 1.149× | 1.148× |
| uv_install_wheel rustc, instructions (billions) | 0.619 | 0.463 | 1.336× | 25.16% | 1.336× | 1.336× |

Control and candidate columns are medians of the original readings. Factors and reductions use the median of the eight matched ratios. Each pair had three separate restores of the same parent per compiler. Bare wall ran the ordinary command. The whole-command counter included Cargo and its descendants. Each per-rustc counter followed one Cargo-launched compiler and its threads, excluding forked children.

- `uv_client` cleared 1× in 8/8 pairs. One-sided exact sign p = 0.00390625, Holm-adjusted p = 0.01171875.
- `sum_of_eight` cleared 1× in 8/8 pairs. One-sided exact sign p = 0.00390625, Holm-adjusted p = 0.01171875.
- `uv_install_wheel` cleared 5/4× in 8/8 pairs. One-sided exact sign p = 0.00390625, Holm-adjusted p = 0.01171875.

The other measurements are descriptive. The full replay checked all 3,404 references to 113 unique compiler metadata products from the complete original. Each measured build matched its own uninstrumented first edit byte-for-byte. Across the four independent cold-B openings, 15 workspace product comparisons had different raw bytes. The decoded public and private definition, expansion and allocation records agreed within each compiler, and all 37 workspace definition and reachable-data shapes agreed between compilers at A, incremental B and cold B.

## Replay the saved measurements

From this directory, run the following with Python 3.10 or later.

```sh
python3 -ISB verify.py --self-test
python3 -ISB verify.py --json
```

The verifier reopens the calibrated hardware readings and kernel process events for all eight rustc processes per role and pair. It checks the complete executable and argument lists against their native Cargo openings and recalculates the pair orders, wall and instruction statistics, both holds and the three threshold tests. The packet retains the two independent producer receipts, both native cache transition fixtures, linked behavior, 486 actual Cargo-unit records and the workspace metadata receipts.

The compressed packet contains 573 byte-exact members from the original. To authenticate it against the full private Actions ZIP or compare current service metadata, run:

```sh
python3 -ISB verify.py --self-test --original /path/to/original.zip
GH_AUTO_ACCOUNT=oss python3 -ISB verify.py --github-cli /home/dev-user/.local/bin/gh-auto
```

The original has artifact ID `13123092911`, 36,278,721 bytes and SHA-256 `5755698027a2a18ffc8706b413b5ed6d799ea683b7c5297718768a6069023331`. A fresh physical rerun requires the two enrolled production SDKs, the signed Cargo binary, an independent calibrated hardware runner, the frozen uv and registry inputs, and the ordinary correctness openings specified by the checked-in workflow at `9720d7075f8b88e1122f4fc258419e58584f4b69`. The earlier admission attempt stopped before its first uv run, and contributes zero observations. [Original zero-pair attempt](https://github.com/astral-experiments/ohm/actions/runs/41403723884)
