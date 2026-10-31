# Rust generic sharing in Ruff's native Unicode generator

At optimization level 1, disabling generic sharing for one real compiler invocation reduced an unchanged `ty_project` check from 9.69B to 7.55B instructions on both workers, a **1.284×** ratio. Moving from the default host opt 0 to this combination gave **2.277× / 2.276×** on the repeat and **2.109× / 2.110×** for the edit and next check together. Package opt 2 alone gave **2.304× / 2.306×** on the repeat. Each arm used the same forwarding workspace wrapper. [Registered protocol](../PLAN.md) · [Original native run](https://github.com/astral-experiments/ohm/actions/runs/41156082521)

Cargo suppresses its shared compiler stages for workspace members when a workspace wrapper is present. An offline comparison against both original unwrapped controls found 254 cold rustcs with `-Zohm-shared-stages` before the wrapper and 223 with it. All 31 differences are workspace compilations. Both setups ran 304 cold rustcs, 48 Wild links and 35 incremental rustcs. On worker 01 the previous ordinary target used 796.00 MiB after the first repeat and the wrapped baseline used 758.23 MiB, with 37.79 MiB of the difference in `target/debug/incremental`. These are fresh, separate targets. The following ratios measure the wrapper-enabled configuration only. [Physical cross-study readback](compared-sham.json) · [Cargo's wrapper condition](https://github.com/astral-experiments/ohm-cargo/blob/761ea115605c34f11a1cd29afd68812c1e1359dd/src/compiler/mod.rs#L270-L283)

Both x86-64 workers ran four fresh installations in mirrored ABQC / CQBA orders and reversed the real historical source edits. A used opt 0, B optimized only `ruff_unicode_names2_generator` at level 1, Q added `-Zshare-generics=no` to that library at level 1, and C used only that package at level 2. They used release-style Cargo `761ea115`, signed `-21` rustc `c79998a5` and signed Wild. The same wrapper path, inode and ctime held for every measurement on the worker. Each command below used the inherited hardware user-instruction counter without tracing. All 56 direct, fork, exec and thread calibration runs passed.

```sh
cargo +ohm check -p ty_project --tests --locked --offline -j8 --message-format=json
cargo +ohm build -p ruff_unicode_names2 --lib --locked --offline -j4 --message-format=json
```

| ty_project check, whole-process instructions | Billions, A / B / Q / C on ABQC | Billions, A / B / Q / C on CQBA | B/Q, by worker | A/Q, by worker |
| --- | --- | --- | --- | --- |
| Cold | 493.325 / 492.157 / 490.769 / 492.038 | 493.235 / 492.143 / 490.762 / 492.065 | 1.003 / 1.003 | 1.005 / 1.005 |
| Unchanged before edit | 16.575 / 9.099 / 6.939 / 6.857 | 16.580 / 9.090 / 6.948 / 6.861 | 1.311 / 1.308 | 2.389 / 2.386 |
| Real edit | 19.439 / 11.972 / 9.822 / 9.726 | 19.457 / 11.975 / 9.819 / 9.729 | 1.219 / 1.220 | 1.979 / 1.982 |
| First unchanged | 17.185 / 9.690 / 7.548 / 7.458 | 17.201 / 9.701 / 7.559 / 7.458 | 1.284 / 1.284 | 2.277 / 2.276 |

The four arms had the same 338-unit Cargo graph, with only the generator's package optimization profile varying between A, B and C. The B and Q graphs were completely equivalent. Every actual cold compiler was accounted for. B and Q had exactly one differing opt/debug/overflow/sharing tuple, where Q's generator got the extra flag. The repeat still ran three full compilers (`build_script_build`, `ron`, `unicode_names2`), one actual Wild link and the generator in each arm. Every successful visit returned 303 typed Cargo artifacts. All three generated Rust files matched, all eight invalid/independently empty observations per worker produced the same E0308, all repairs were clean, and checked overflow and debug assertions held. The two hosts separately ran 36 native-provider commands, including higher-priority 83→47 with the same inode, size and mtime, malformed rejection, removal and independent empty references. [Complete raw verdicts and ratios](verified.json)

| Unicode linked library build | Billions, A / B / Q / C on ABQC | Billions, A / B / Q / C on CQBA | B/Q, by worker | A/Q, by worker |
| --- | --- | --- | --- | --- |
| Cold | 24.998 / 23.844 / 22.503 / 23.724 | 25.005 / 23.894 / 22.460 / 23.766 | 1.060 / 1.064 | 1.111 / 1.113 |
| Unchanged before edit | 14.123 / 6.651 / 4.489 / 4.395 | 14.118 / 6.638 / 4.500 / 4.387 | 1.482 / 1.475 | 3.146 / 3.137 |
| Real generator edit | 14.717 / 9.520 / 7.745 / 9.165 | 14.708 / 9.521 / 7.744 / 9.167 | 1.229 / 1.229 | 1.900 / 1.899 |
| First unchanged | 14.719 / 7.324 / 5.095 / 5.004 | 14.743 / 7.318 / 5.090 / 5.070 | 1.437 / 1.438 | 2.889 / 2.897 |

The secondary build compiled and ran a reader against each returned library. Its four codepoints and raw executable matched the independently empty reference in each arm. Its wrapped repeat ran two rustcs and a real Wild link. The previous unwrapped repeat ran one rustc and one Wild link. Natural package opt 2 beat Q on repeat and Q used fewer instructions on the real generator edit. [Prior unwrapped comparison](https://github.com/astral-experiments/ohm/tree/e2dffc67a5a3eeab53b8e1fcded93f7896dc325c/scripts/strict-one-package/result)

After the primary repeat, unique target and shared allocation for A/B/Q/C was 758.234 / 757.227 / 756.848 / 756.680 MiB and 758.223 / 757.215 / 756.844 / 756.672 MiB. Q saved 0.379 and 0.371 MiB versus B. Both comparisons saved 0.328 MiB in `target/debug/build` and 0.016 MiB in cross-directory hard-link aliases, counted once. The incremental-directory differences were 0.035 and 0.027 MiB. The wrapper's controlling environment is outside Cargo's tracked profile, so this study used fresh roots for every mode and did not test a B/Q upgrade or coexistence. The earlier package-only study measured 388.23 MiB of additional mixed-state storage. Two workers provide descriptive directional evidence.

The original GitHub ZIPs are stored here byte-for-byte, with their size, SHA-256 digest and provenance in adjacent JSON. They include neutral generator ELFs, libraries, kernel argv, actual externals, per-inode storage, counters and clean references. Run from this directory:

```sh
python3 -IB reopen.py . | cmp - verified.json
python3 -IB extract.py . 01 /tmp/ohm-generic-sharing-outputs
# Optional, using the linked unwrapped packet
python3 -IB compare_sham.py /path/to/strict-one-package/result . | cmp - compared-sham.json
```
