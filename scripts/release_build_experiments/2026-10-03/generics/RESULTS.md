# Measured generic-sharing results

Times are wall-clock seconds. Each off/on pair uses the same Cargo executable on the same host, with default concurrency. Off disables the prototype; on enables `-Zohm-lto-share-generics`. Every numeric row below has completed successfully without observed foreign compiler activity or Cargo lock waits. Incomplete stages remain in the machine-readable summary and are omitted from this table.

| Workload | Host             | LTO  | Pair / order | Stage        | Off (s) |  On (s) |  Change |
| -------- | ---------------- | ---- | ------------ | ------------ | ------: | ------: | ------: |
| uv       | charlie-openai-2 | fat  | 1 / BA       | cold         | 693.746 | 558.559 | -19.49% |
| uv       | charlie-openai-2 | fat  | 1 / BA       | edit         | 564.992 | 445.124 | -21.22% |
| uv       | charlie-openai-2 | fat  | 1 / BA       | library-edit | 629.169 | 496.957 | -21.01% |
| uv       | charlie-openai-3 | fat  | 1 / AB       | cold         | 661.528 | 539.104 | -18.51% |
| uv       | charlie-openai-3 | fat  | 1 / AB       | edit         | 554.823 | 435.556 | -21.50% |
| uv       | charlie-openai-3 | fat  | 1 / AB       | library-edit | 604.725 | 486.662 | -19.52% |
| ruff     | charlie-serc-1   | fat  | 1 / BA       | cold         | 245.156 | 253.812 |  +3.53% |
| ruff     | charlie-serc-1   | fat  | 1 / BA       | edit         | 194.948 | 205.379 |  +5.35% |
| ruff     | charlie-serc-1   | fat  | 1 / BA       | library-edit | 239.613 | 244.514 |  +2.05% |
| ruff     | charlie-serc-1   | fat  | 2 / AB       | cold         | 243.001 | 251.504 |  +3.50% |
| ruff     | charlie-serc-1   | fat  | 2 / AB       | edit         | 195.191 | 207.408 |  +6.26% |
| ruff     | charlie-serc-1   | fat  | 2 / AB       | library-edit | 240.041 | 243.943 |  +1.63% |
| ruff     | charlie-serc-1   | thin | 1 / AB       | cold         |  62.031 |  59.725 |  -3.72% |
| ruff     | charlie-serc-1   | thin | 1 / AB       | edit         |  14.971 |  15.058 |  +0.58% |
| ruff     | charlie-serc-1   | thin | 1 / AB       | library-edit |  60.000 |  56.211 |  -6.32% |
| uv       | charlie-serc-3   | fat  | 1 / AB       | cold         | 724.451 | 543.743 | -24.94% |
| uv       | charlie-serc-3   | fat  | 1 / AB       | edit         | 568.520 | 444.770 | -21.77% |
| uv       | charlie-serc-3   | fat  | 1 / AB       | library-edit | 610.044 | 497.089 | -18.52% |
| uv       | charlie-serc-3   | thin | 1 / AB       | cold         | 176.238 | 153.164 | -13.09% |
| uv       | charlie-serc-3   | thin | 1 / AB       | edit         |  73.306 |  49.984 | -31.81% |
| uv       | charlie-serc-3   | thin | 1 / AB       | library-edit | 124.551 | 101.190 | -18.76% |

## Cold executable size

| Workload | Host             | LTO  | Pair | Off (bytes) | On (bytes) |  Change |
| -------- | ---------------- | ---- | ---- | ----------: | ---------: | ------: |
| uv       | charlie-openai-2 | fat  | 1    |  55,528,536 | 49,395,128 | -11.05% |
| uv       | charlie-openai-3 | fat  | 1    |  55,520,344 | 49,391,096 | -11.04% |
| ruff     | charlie-serc-1   | fat  | 1    |  29,372,587 | 29,756,693 |  +1.31% |
| ruff     | charlie-serc-1   | fat  | 2    |  29,372,587 | 29,756,693 |  +1.31% |
| ruff     | charlie-serc-1   | thin | 1    |  37,548,127 | 40,184,279 |  +7.02% |
| uv       | charlie-serc-3   | fat  | 1    |  55,527,640 | 49,394,232 | -11.05% |
| uv       | charlie-serc-3   | thin | 1    |  64,738,560 | 58,955,576 |  -8.93% |

## Cold CPU time and memory

GNU time user and system CPU seconds include work charged to the command and its children. Maximum RSS is the process/child high-water figure, not aggregate concurrent compiler memory.

| Program | Host             | LTO / pair | Off CPU s (user + sys) | On CPU s (user + sys) | Off / on max RSS (KiB) |
| ------- | ---------------- | ---------- | ---------------------: | --------------------: | ---------------------: |
| uv      | charlie-openai-2 | fat / 1    |       1555.63 + 209.75 |      1259.76 + 201.85 |  6,021,084 / 5,026,892 |
| uv      | charlie-openai-3 | fat / 1    |       1499.27 + 201.35 |      1223.74 + 186.84 |  6,059,172 / 5,049,920 |
| ruff    | charlie-serc-1   | fat / 1    |        761.71 + 268.66 |       736.19 + 268.26 |  2,748,216 / 2,758,508 |
| ruff    | charlie-serc-1   | fat / 2    |        767.06 + 239.60 |       732.03 + 270.37 |  2,724,120 / 2,767,480 |
| ruff    | charlie-serc-1   | thin / 1   |        855.02 + 309.64 |       837.98 + 248.43 |  2,660,824 / 2,754,728 |
| uv      | charlie-serc-3   | fat / 1    |       1718.18 + 354.36 |      1362.85 + 305.77 |  6,051,048 / 5,083,172 |
| uv      | charlie-serc-3   | thin / 1   |       1768.44 + 395.58 |      1530.05 + 405.78 |  4,703,444 / 4,344,976 |

## Runtime

Only cohorts passing the post hoc exit-code, stdout, and diagnostic audit appear below. Each uses 30 randomized pairs after three warmups per executable and workload. The interval bootstraps paired ratios; it describes this corpus and host, not all production use.

| Program | Host             | LTO  | Workload | Pairs | On/off geomean | 95% interval  |
| ------- | ---------------- | ---- | -------- | ----: | -------------: | ------------- |
| uv      | charlie-openai-2 | fat  | jupyter  |    30 |         0.9897 | 0.9744–1.0058 |
| uv      | charlie-openai-2 | fat  | trio     |    30 |         0.9849 | 0.9684–1.0025 |
| uv      | charlie-openai-3 | fat  | jupyter  |    30 |         1.0004 | 0.9793–1.0228 |
| uv      | charlie-openai-3 | fat  | trio     |    30 |         1.0463 | 0.9770–1.1750 |
| ruff    | charlie-serc-1   | fat  | check    |    30 |         1.0087 | 0.9924–1.0257 |
| ruff    | charlie-serc-1   | fat  | format   |    30 |         1.0071 | 1.0044–1.0099 |
| ruff    | charlie-serc-1   | thin | check    |    30 |         1.0306 | 1.0090–1.0547 |
| ruff    | charlie-serc-1   | thin | format   |    30 |         1.0097 | 1.0049–1.0145 |
| uv      | charlie-serc-3   | fat  | jupyter  |    30 |         0.9663 | 0.9241–1.0042 |
| uv      | charlie-serc-3   | fat  | trio     |    30 |         0.9530 | 0.8914–0.9973 |
| uv      | charlie-serc-3   | thin | jupyter  |    30 |         1.0174 | 0.9974–1.0415 |
| uv      | charlie-serc-3   | thin | trio     |    30 |         1.0045 | 0.9856–1.0229 |

## Exploratory global-flag screen

These rows use the released Cargo and globally inject `-Zshare-generics=yes`. They are separate from the actual policy above.

| Workload | Host           | Stage        | Off (s) | Global flag (s) | Change |
| -------- | -------------- | ------------ | ------: | --------------: | -----: |
| ruff     | charlie-serc-1 | cold         | 244.291 |         250.234 | +2.43% |
| ruff     | charlie-serc-1 | edit         | 196.902 |         205.701 | +4.47% |
| ruff     | charlie-serc-1 | library-edit | 240.616 |         245.516 | +2.04% |

The uv global candidate was skipped before launch after the Ruff regression so compute could measure the scoped Cargo policy. Its completed baseline remains in the raw evidence.

## Conditions and scope

- Cold means fresh isolated Cargo target and build directories; registry and OS file caches are warm.
- Default concurrency, existing security/system services retained; outside-process CPU and steal time are recorded.
- GNU time maximum RSS is its process/child high-water figure, not peak aggregate memory across concurrent compiler processes.
- Initial global-RUSTFLAGS screen and actual graph-scoped Cargo policy are separate cohorts.
- Entry edit inserts a black_box string at main. Library edit changes a generic deserializer error message on top of that entry edit.
- Runtime uses unedited cold binaries; Ruff checks/formats pinned CPython with no cache; uv resolves two pinned inputs offline against a warmed public PyPI cache.
- Fat-LTO uv confirmations run on three separate hosts; ratios are reported per host. Ruff uses counterbalanced within-host pairs. ThinLTO is a single-pair exploratory profile screen.
- Rejected idle preflights are retained. Resumes preserve completed samples, original checkpoints, and stage-specific runner hashes; they do not rerun or replace successful timings.
- Raw compiler/process logs, Cargo timing reports, and original runtime streams are retained in checksummed host archives. See README.md for pinned inputs and exact reproduction.
