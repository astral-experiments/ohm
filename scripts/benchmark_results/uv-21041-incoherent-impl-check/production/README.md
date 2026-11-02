# Foreign inherent impls on the uv-client check

On the real uv [#21041 edit](https://github.com/astral-sh/uv/pull/21041), the production change reduced retired userspace instructions in the `uv_metadata` rustc by **20.0965%**. All eight independently restored pairs cleared the predeclared 20% threshold. Candidate/control medians were 0.799042 and 0.799032 across the two histories, with exact one-sided sign-test p = 0.00390625. [Original production run](https://github.com/astral-experiments/ohm/actions/runs/41423715247)

The command was `cargo check -p uv-client --locked --offline -j8`. All eight rustcs used fewer instructions in every pair. Their sum fell 2.95%. Plain blocking-wait wall time improved 2.33% by median paired ratio, with seven faster pairs and zero reaching 2×. `uv_metadata` was the sole prespecified threshold endpoint. The eight-compiler sum and individual secondary rows describe the observed workload.

| Endpoint | Control median | Treatment median | Paired reduction | Pairs improved |
| --- | ---: | ---: | ---: | ---: |
| `uv_metadata` | 172,257,169.5 | 137,640,055 | 20.10% | 8/8 |
| `uv_cache` | 365,628,651.5 | 326,216,638.5 | 10.78% | 8/8 |
| `uv_install_wheel` | 463,337,137 | 416,757,357 | 10.05% | 8/8 |
| `uv_torch` | 383,092,306.5 | 354,368,766.5 | 7.50% | 8/8 |
| `uv_distribution_types` | 2,031,393,593 | 1,973,572,701 | 2.85% | 8/8 |
| `uv_client` | 3,103,226,490.5 | 3,050,592,551 | 1.70% | 8/8 |
| `uv_configuration` | 808,896,604.5 | 796,933,216 | 1.48% | 8/8 |
| `uv_pypi_types` | 1,964,665,765.5 | 1,962,296,617 | 0.12% | 8/8 |
| `sum_of_eight` | 9,292,482,786.5 | 9,018,384,043.5 | 2.95% | 8/8 |
| `wall` | 1.247566 s | 1.220008 s | 2.33% | 7/8 |

Compiler values give retired instructions for each actual rustc and its threads. Wall time comes from a separate uninstrumented restoration. For a constituent with an even number of observations, the median of integer counts may end in .5. The paired percentage uses the median of per-pair candidate/control ratios.

The control is the optimized Ohm −22 compiler with #318, #296, #306 and the callable lookup patch. The treatment adds the per-crate foreign inherent-impl query on the same production recipe. Both run the Cargo binary from the signed −22 GNU release on the real landed uv edit #21041.

The primary is retired userspace instructions in the actual uv_metadata rustc and its threads. Each of two independently built prior-edit histories supplies four counterbalanced pairs. The preregistered result requires both four-pair median cost ratios below 0.80 and a one-sided exact sign test at 0.05 across all eight pairs. Ties count against qualification.

Each visit restores that role's original A checkpoint and applies the source edit. The collector enrolls the eight exact compiler commands Cargo ran. It retains their individual PMUs and sum, alongside a separate uninstrumented, blocking-wait Cargo visit. These secondary measurements are descriptive. The native regression covers foreign and local impl transitions, an actual signature error, warm/cold equality, default rejection across the changed compiler epoch, and each compiler's own incremental reuse.

The artifacts include the signed Cargo and production SDK receipts, original clocks and counters, kernel image records, and Cargo output and semantic metadata checks for every history.

To replay all 128 genuine rustc counter records and 16 separate Cargo clocks, run `python3 -ISB verify.py --self-test`. The optional `--original PATH` compares every included record to the service ZIP. `origin.json` identifies the untouched original and the independent full semantic replay. A fresh physical run needs the original SDKs, the signed Cargo, new cold histories and a newly calibrated machine.

Two earlier attempts stopped before any scored visit. The first failed at the unchanged-command observer. The second completed a normal control A→B and independent cold B but lacked a runtime copy of the eight-command hash already present in the original plan. `python3 -ISB verify_attempts.py` reopens both complete service ZIPs and checks their actual evidence, original source and prospective argv. Their zero pairs are excluded from this result.
