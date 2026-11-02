# Hardware counters for uv #21041

The landed edit changed the PyPI and Pyx parser. Eight paired trials ran `cargo check -p uv-client --locked --offline -j8` after restoring a warmed parent and applying the genuine unstaged edit. The optimized stage1 control was `26210096`. The candidate `f2282534` recovers callable trait-lookup keys during incremental compilation. Both used the same signed Ohm −22 Cargo. [Real uv edit](https://github.com/astral-sh/uv/pull/21041) · [Original Actions job](https://github.com/astral-experiments/ohm/actions/runs/41399090905/job/125126764197)

| Endpoint | Median paired speedup | Reduction | Hold 1 | Hold 2 |
| --- | ---: | ---: | ---: | ---: |
| Ordinary Cargo wall | 1.112× | 10.04% | 1.083× | 1.128× |
| Whole-Cargo userspace instructions | 1.136× | 11.96% | 1.136× | 1.136× |
| Instructions summed over eight real rustcs | 1.141× | 12.37% | 1.141× | 1.141× |
| Terminal `uv_client` instructions | 1.167× | 14.28% | 1.167× | 1.167× |
| `uv_install_wheel` instructions | 1.366× | 26.80% | 1.366× | 1.366× |

The two holds each started from independently built parent targets for both compilers on one machine. Every pair used separate restored first edits for plain wall, whole-command inherited userspace instructions and kernel-observed per-rustc counters. The latter count each compiler and its threads. Sixteen fresh process traces cover 128 compiler invocations across all eight dirty crates. Every pair favored the candidate for every individual compiler, total, whole-Cargo count and plain wall. Whole-command wall medians were 1.967 s and 1.792 s. The table reports medians of matched pair ratios.

Terminal rustc and the sum of all eight were tested against parity. A prior guest-instruction screen selected `uv_install_wheel` for the separate hardware test against a 20% instruction reduction (control/candidate greater than 1.25). All three one-sided exact paired sign tests gave raw p = 0.00390625 and Holm-adjusted p = 0.01171875. The other endpoints are descriptive. These two compilers share an experimental stage1 base. A clean production build is a separate comparison.

## Reproduce

Run from this directory with Python 3.10 or later. The verification uses the standard library.

```sh
python3 -ISB verify.py --self-test
python3 -ISB verify.py --json
```

The verifier reads the calibrated raw counters, joins each compiler’s PID and complete argv to a successful Cargo process from Linux kernel event records, and rederives every paired result. It checks the 486 actual units, 37 workspace products, original source, parent checkpoints, linked behavior and warm/cold semantic receipt equality. The hostile tests change genuine records in memory and require refusal.

`evidence.tar.xz` contains 561 byte-exact original members (26,904,364 uncompressed bytes, 131,744 packaged bytes). These include all 48 enrolled first edits, both native cache-compatibility checks, the per-role Cargo rosters, and each original PMU and wall record. The full original also includes the compiler metadata files. Before packaging, a separate replay decoded all 114 unique original rmeta files across 2,960 product references. Independent cold builds sometimes emitted a different byte layout. The tracked public and private headers, definitions, expansions and allocations agreed within each compiler, and every measurement from the same parent checkpoint matched byte-for-byte.

The original Actions ZIP is 37,771,404 bytes, ID `13120249254`, with SHA-256 `a920d8c6d95a903e156f098055d2342466505927f9c42adc77878a2227dfbb76`. If the original ZIP is available, the following command also checks every selected member against it. The optional GitHub check queries the private repository, job, commit and artifact metadata while the hosted original remains available.

```sh
python3 -ISB verify.py --self-test --original /path/to/original.zip
GH_AUTO_ACCOUNT=oss python3 -ISB verify.py --github-cli /home/dev-user/.local/bin/gh-auto
```
