# Stable generated-impl identities after uv #21041

The last compiler process, `uv_client`, executed 12.026% and 12.035% fewer instructions after the landed edit to [uv](https://github.com/astral-sh/uv/pull/21041). Across the eight rustc processes that Cargo actually ran, the corresponding reductions were 4.893% and 4.896%. These are two balanced stage1 screening pairs measured with Callgrind. Production hardware counters and ordinary check wall time have a separate prospective experiment.

The change gives generated trait implementations a stable identity when a new derive appears above them. Each visit compiled revision `a2a02424dcba3c3f37cf6b8de5484497dd48651e` from scratch, checked it unchanged, applied the actual landed change to `crates/uv-pypi-types/src/simple_json.rs` at `9049e07fa6b8e4863807b3a6e6e1293cbf68d0c3`, then checked the new revision with signed Cargo. The ordinary command was `cargo check -p uv-client --locked --offline -j8`. The off-clock validation repeated B unchanged and clean, compared all 37 workspace compiler products and ran the linked behavior checks. The visit order was parent, candidate, candidate, parent, with four independent A seeds.

| Rustc process | Instructions saved, first pair | Instructions saved, second pair |
| --- | ---: | ---: |
| `uv_cache` | +0.015% | +0.034% |
| `uv_client` | +12.026% | +12.035% |
| `uv_configuration` | -0.015% | -0.014% |
| `uv_distribution_types` | +0.592% | +0.564% |
| `uv_install_wheel` | +0.015% | +0.009% |
| `uv_metadata` | +0.027% | -0.039% |
| `uv_pypi_types` | +2.832% | +2.844% |
| `uv_torch` | -0.036% | +0.049% |
| All eight rustc processes | +4.893% | +4.896% |

The terminal rustc counts were 5,090,897,288 to 4,478,679,155 and 5,090,189,889 to 4,477,575,358. All eight summed to 14,807,422,836 to 14,082,893,879 and 14,805,395,924 to 14,080,527,200. Recounting includes every compiler process in the observed source-edit transition. Callgrind wall time is excluded.

### Cold compilation and ordinary build

The eight cold terminal captures cover both revisions and both independently initialized pairs. Candidate instruction changes were -0.173% and +0.122% on revision A and +0.050% and +0.143% on revision B.

The independent ordinary `cargo build --locked --offline -j8 -p uv-cli` check used another landed edit, [uv #20992](https://github.com/astral-sh/uv/pull/20992). It ran four fresh A seeds and retained the first B build from every visit. The pairs were 6.6781 to 6.4535 seconds and 7.1559 to 9.0058 seconds. One visit regressed 25.85%. The results disagree, so build nonregression remains open. The [production guard](production-build-guard-registration.json) requires a candidate/parent median below 1.05 in both four-pair groups and at least seven individual ratios below 1.10.

### Recompute the screening results

Run `python3 -ISB verify.py` beside the two original Callgrind archives and their manifests. It reopens all 32 edited and eight cold profiles, verifies every compressed member, reconstructs each process count and separately checks the native capture and source-edit receipts.

Run `python3 -ISB verify-build-guard.py` to verify the four original ordinary-build clocks, complete Cargo logs and native admission receipts, then recompute both ratios. The build archive also retains the experiment registration, result, native and wall-clock oracles, and full replay entry point. Regenerating the large native binary and archive comparisons requires the registered SDKs and original target directories.

The published [prospective screen](../preregistration), [production registration](../production-registration) and [production toolchain build](https://github.com/astral-experiments/ohm/actions/runs/41434876352) identify the exact compiler roles and promotion criteria.
