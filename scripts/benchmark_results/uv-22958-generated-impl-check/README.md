# A 2.15× faster edited uv client check

The cumulative rustc stack reduced the median wall time of `cargo check -p uv-client --locked --offline -j8` from 1.327 s to 0.615 s after applying uv’s eight-file workspace metadata schema change. The paired median speedup was 2.151×. All eight pairs were above 2×, from 2.080× to 2.243×. The four-pair medians were 2.172× and 2.142×. The exact one-sided sign test at 2× gives p = 1/256. [uv edit](https://github.com/astral-sh/uv/pull/22958) · [Original run](https://github.com/astral-experiments/ohm/actions/runs/41447094828)

| Measure | Corrected Ohm −22 median | Full stack median | Paired median speedup | Pairs above 2× |
| --- | ---: | ---: | ---: | ---: |
| Ordinary Cargo wall time | 1.327 s | 0.615 s | 2.151× | 8/8 |
| Both rustc processes | 8.713B instructions | 3.366B instructions | 2.588× | 8/8 |
| `uv_client` rustc | 6.431B instructions | 2.086B instructions | 3.082× | 8/8 |
| `uv_configuration` rustc | 2.283B instructions | 1.280B instructions | 1.783× | 0/8 |
| Whole Cargo process tree | 9.562B instructions | 4.215B instructions | 2.269× | 8/8 |

Both compilers used the same signed Ohm −22 Cargo and the same production build recipe. The control was `10d56274`, which includes the CTFE correctness fix. The signed release compiler had failed the cold identity check on this edit. The treatment was `ac67101c`, the cumulative compiler through the generated-impl change. [Control correction](https://github.com/astral-experiments/ohm-rust/pull/318) · [Treatment build](https://github.com/astral-experiments/ohm/actions/runs/41434876352)

One fresh worker ran eight counterbalanced pairs. Each of the sixteen histories began with an independently built A state. Bare timing used a blocking wait for Cargo. Separate visits restored the same seed for the whole-command and per-rustc retired userspace instruction counts. The 38 kernel traces contain 68 compiler images. Each edited trace contains exactly the two expected rustc processes, and each unchanged trace contains zero. [Harness and input revisions](https://github.com/astral-experiments/ohm/tree/651801e3029fb35b79768116c57bfe3e8d36d57a/scripts/uv-client-22958)

The previous stack cleared 2× in six of eight pairs on this edit. This comparison’s primary endpoint and edit were recorded before the optimized treatment SDK existed. The decision to run it was recorded after the separate generated-impl marginal test on uv #21041 missed its 20% terminal target. On that other edit, the individual change reduced terminal `uv_client` instructions by 10.05%, reduced instructions across all eight rustc processes by 4.02%, and sped up ordinary Cargo wall time by 1.051×. It also passed the ordinary build guard on uv #20992. [Marginal check evidence](https://github.com/astral-experiments/ohm/tree/5e7fffae5b85b5024aac3c59d666eaec2ca8e1b3/scripts/benchmark_results/uv-21041-generated-impl-check/production-marginal) · [Build evidence](https://github.com/astral-experiments/ohm/tree/15273896ecdc6bcb35292304648999f91c799af3/scripts/benchmark_results/uv-20992-production-build-guard)

## Reproduce the measurements

Run `python3 -ISB verify.py` in this directory to recompute all eight pairs from the 394 retained original records. To verify every one of the 3,703 original members against its SHA-256, download the Actions artifact identified in `original-service.json` and run `python3 -ISB verify.py --original PATH/TO/ORIGINAL.zip`. The raw service ZIP is 130,607,791 bytes with SHA-256 `7448509275ec704eb383bf9803ce93769f9eba5c4894b77ef983427782c9dcde`.

The immutable workflow head, original public uv commits, both SDK sources, signed Cargo digest, run order, cold controls and timing rules are in the registration and release lock. The accompanying replication plan holds these fixed for another fresh worker. [Original workflow](https://github.com/astral-experiments/ohm/blob/651801e3029fb35b79768116c57bfe3e8d36d57a/.github/workflows/ci.yml)
