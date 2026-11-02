# Wall time after uv #21041

`cargo check -p uv-client --locked --offline -j8` took a median of 1822.1 ms on corrected Ohm −22, 1361.1 ms with the existing trait changes and 1247.3 ms after adding callable recovery. The paired speedups were **1.093×** for the callable change and **1.456×** for the full stack. The full stack cleared 2× in **0/12** trios. [Original run](https://github.com/astral-experiments/ohm/actions/runs/41411015186) · [Real uv edit](https://github.com/astral-sh/uv/pull/21041)

| Comparison | Paired median | Each independent A history | Above threshold | Holm-adjusted one-sided p |
|---|---:|---:|---:|---:|
| Callable over mature stack | 1.0928× | 1.0920× / 1.0943× | 12/12 above 1× | 0.000488281 |
| Cumulative over corrected −22 | 1.4562× | 1.4545× / 1.4594× | 0/12 above 2× | 1 |

The third comparison, mature versus corrected −22, was descriptive. Its median paired speedup was 1.3341×, with history medians of 1.3341× and 1.3331×. It was faster in 12/12 trios.

All three production compilers used signed −22 Cargo and the CTFE correction from #318. The mature stack contains #296 and #306. The last arm adds the source of #327. Each of the two independently built A histories used all six compiler orders on one fresh eight-core allocation. Each clock covers ordinary Cargo from immediately before process launch through its blocking exit wait.
The native short-child calibration added median overheads of 0.384 ms before and 0.414 ms after the clocks. The largest overhead among all 50 controls was 0.697 ms.

## Separately restored Cargo timelines

| History | Signed Cargo diagnostic CLI | First unit starts | Last unit finishes | Terminal-only uv-client tail | Last other unit |
|---|---:|---:|---:|---:|---|
| 1 | 1274.2 ms | 109.9 ms | 1256.0 ms | 473.0 ms | uv_configuration |
| 2 | 1270.2 ms | 105.9 ms | 1252.3 ms | 474.0 ms | uv_configuration |

The independent, nonverbose Cargo diagnostics expose 15 direct dependencies among eight launched compilers. The consumers started while their producer was still running on 9 and 9 of these edges. Both unchanged repeats launched zero compilers. The raw logs explicitly label 0 and 0 unblocks. Their metadata and start timestamps bound the other releases. Cargo handles conditional-metadata notifications without recording a timing event. See [the signed Cargo scheduler](https://github.com/astral-experiments/ohm-cargo/blob/ed0ae15d22da9a0af9afb3d0fdeb4ceb8a71b770/src/compiler/job_queue/mod.rs#L1528-L1542).

The per-trio median distance from a halving of the corrected −22 wall was 338.2 ms. Each logged visit uses an additional Cargo diagnostic option. Its absolute time is separate from the twelve bare trios.

## Replay

Run `python3 -ISB verify.py` in this directory. The reader hashes every retained member, checks the balanced schedule, actual boot and clock calibration, and computes the median paired ratios and exact sign tests from all 36 original nanosecond clocks. It also reports every bare sample and Cargo’s secondary Finished display, which resolves 10 ms on these commands. The SHA-256 of the larger original service archive is in `manifest.json`. That larger archive contains the raw compiler metadata and native qualification.

The packet recalculates the recorded experiment. A fresh physical run additionally needs the pinned source, signed Cargo, three authenticated SDK artifacts, independent warmed A states and a calibrated runner.

With the larger original, `python3 -ISB verify.py --original /path/to/original.zip` also checks the service ZIP digest and compares every source result member byte for byte. The four additional members are the preregistration, its plan, the SDK lock and the service metadata projection.
