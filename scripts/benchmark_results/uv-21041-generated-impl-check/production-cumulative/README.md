# Cumulative production rustc instructions after uv #21041

The sum of eight Cargo-launched rustc processes went from 17.244564B to 8.656352B median retired userspace instructions. The median paired ratio was 1.992132×. The four-pair medians were 1.992184× and 1.992071×. 0/8 pairs exceeded 2×, with exact one-sided sign-test p = 1. The result missed the preregistered threshold of eight strict wins and both history medians above 2×. [Prospective scope](https://github.com/astral-experiments/ohm/blob/4693ee1baebc5bc2a000fac534aa4ae98b9bacd6/scripts/benchmark_results/uv-21041-generated-impl-check/production-registration/cumulative-instructions.json)

The command was `cargo check -p uv-client --locked --offline -j8` after applying the one-file uv change from `a2a02424` to `9049e07f`. Both arms used the same signed Ohm −22 Cargo. The control was the release-optimized −22 compiler with #318 corrected (`10d56274`), and the treatment was the cumulative production compiler at `ac67101c`. The original records bind both SDK distributions, compile provenance and actual drivers. [uv change](https://github.com/astral-sh/uv/commit/9049e07fa6b8e4863807b3a6e6e1293cbf68d0c3)

Each arm started from two independent warm A histories. Within each history the two orders ran twice. Each rustc counter covers one kernel-identified compiler process and its threads. The whole-Cargo counter includes the full inherited process tree on a separate restore. Bare wall uses a third restore with the uninstrumented command and a blocking wait. All 128 scoped compiler invocations matched their enrolled argv, and the eight unchanged controls started zero compiler processes. Both histories passed the native artifact, metadata and linked-behavior checks. This is a single physical host.

| Endpoint | Control median | Treatment median | Median paired control/treatment | Pairs over 2× |
| --- | ---: | ---: | ---: | ---: |
| Eight rustcs summed (primary) | 17.244564 B | 8.656352 B | 1.992132× | 0/8 |
| uv_cache | 0.658224 B | 0.326011 B | 2.019022× | 8/8 |
| uv_client | 5.735561 B | 2.744025 B | 2.090206× | 8/8 |
| uv_configuration | 1.631753 B | 0.796827 B | 2.047815× | 8/8 |
| uv_distribution_types | 3.721662 B | 1.966016 B | 1.892997× | 0/8 |
| uv_install_wheel | 1.135319 B | 0.416522 B | 2.725716× | 8/8 |
| uv_metadata | 0.307823 B | 0.137578 B | 2.237461× | 8/8 |
| uv_pypi_types | 3.324199 B | 1.915141 B | 1.735744× | 0/8 |
| uv_torch | 0.730010 B | 0.354239 B | 2.060790× | 8/8 |
| Whole Cargo instruction count | 17.834376 B | 9.246060 B | 1.928868× | 0/8 |
| Bare Cargo wall | 1.827403 s | 1.162093 s | 1.573800× | 0/8 |

Run `python3 verify.py` with Python 3.11+ to verify the checksums, orders, raw hardware readings and paired estimates. Supplying `--original /path/to/zip` also authenticates the Actions upload, reads the original kernel events and clocks, and reproduces the compact inputs. A fresh physical experiment uses new native A histories, calibrated hardware, and the same two production distributions. [Hosted measurement and original](https://github.com/astral-experiments/ohm/actions/runs/41447859570)

The prior, independently hosted linked-build safeguard is also reproducible from its separate packet. [uv #20992 linked-build guard](https://github.com/astral-experiments/ohm/tree/15273896ecdc6bcb35292304648999f91c799af3/scripts/benchmark_results/uv-20992-production-build-guard)

Original artifact 13143084322, 143,431,627 bytes, SHA-256 `3caa9fd7eba7b3f1b371727aee4da0b8396726c31b7be0091cbf75350fa81102`. The SDK lock is `51d3b6c65b320f8e7d40021e805475a64ad8de9fa3257530f3069804a7fb1ce0`. The coordinator is `1c09d403e702da036a80a1d4ac54937b57bde9ad`.

The full independent native replay used the original corrected-stock three-job, five-artifact producer and the generated-derive single-job, two-artifact producer. The initial offline reader selected the newer producer schema for both arms. The corrected replay authenticated both original service records and rejected a modified QA digest independently for each arm. The prospective worker had used the separate original validators throughout.
