# Production rustc instructions after uv #21041

The generated-derive change reduced the terminal `uv_client` rustc's instructions by **10.05%** in ordinary `cargo check -p uv-client --locked --offline -j8`. All eight pairs improved. Zero pairs beat the registered 20% reduction, so the release-optimized compiler missed that threshold. The separate blocking-wall measurement improved by 1.0512×. [Actual uv edit](https://github.com/astral-sh/uv/pull/21041) · [Original private run](https://github.com/astral-experiments/ohm/actions/runs/41441663949)

| Endpoint | Control median | Candidate median | Median paired control/candidate |
|---|---:|---:|---:|
| Terminal `uv_client` rustc | 3.05051B instructions | 2.74390B instructions | 1.11175× |
| Sum of eight rustcs | 9.01838B instructions | 8.65622B instructions | 1.04184× |
| Whole Cargo process tree | 9.60824B instructions | 9.24596B instructions | 1.03917× |
| Bare Cargo wall | 1.22556 s | 1.16379 s | 1.05120× |

The control was `77ce0545`, including the CTFE, trait lookup and foreign inherent-impl fixes. The candidate `ac67101c` added stable identities for eligible procedural-derive impls. Both used native production PGO, BOLT, ThinLTO and the same signed Ohm −22 Cargo. The real edit changed `crates/uv-pypi-types/src/simple_json.rs` at `a2a02424→9049e07f`. The two independently constructed histories had terminal candidate/control median ratios of 0.899464 and 0.899496. The exact one-sided sign p-value at 0.80 was 1. [Registered sources and native worker](https://github.com/astral-experiments/ohm/tree/e12e6778ebfaf38ea35fdd8a4084230f6bf1b937/scripts/uv-callables-21041)

Each meter had its own ordinary first check restored from A. The process counter counted each actual rustc PID and its threads. The sixteen process traces contained 128 compiler execs, all eight expected compilation units per visit, and zero additional identification probes. The eight unchanged-control traces contained zero rustc execs. The clock used a blocking wait and a separate watchdog. All observations came from one newly calibrated machine. The two history orders were PC/CP/CP/PC and CP/PC/PC/CP, with P for control and C for candidate.

The native openings checked 37 workspace products, 415 public sidecars, eight selected compiler command lines and the linked PyPI/PyX behavior. The typed metadata reader examined every definition and expansion on both compilers at A, edited B and independently cold B. It matched 1,048 generated impl owners across the releases, covering 8,331 migrated keys. Within each compiler, the six enrolled rkyv impls moved on the control and stayed stable on the candidate. The independent cold comparisons retained raw-layout differences where the native semantic record matched. The original dataset preserves the underlying metadata and source. [Metadata decoder](https://github.com/astral-experiments/ohm/blob/e12e6778ebfaf38ea35fdd8a4084230f6bf1b937/scripts/uv-callables-21041/derive/panel.py)

Run `python3 -ISB verify.py` here to reconstruct every paired point and the registered threshold. With the service ZIP from the original run, `python3 -ISB verify.py --original /path/to/original.zip` also checks the service SHA-256, raw PMU bytes, all rustc kernel execs, eight zero-launch controls, clock inputs and the per-hold metadata receipts. A fresh physical rerun requires the release SDKs, pre-enrolled real edit and an independent Linux machine. The complete source provenance, original member fingerprints and raw measurements are in `origin.json`, `samples.json.gz` and `paired.json`.

One ancillary field in the inherited worker output, `native-rustc.json.primary`, retained the older `uv_metadata` label. The frozen study, the applied threshold and `primary_test.primary` all select `uv_client`.
