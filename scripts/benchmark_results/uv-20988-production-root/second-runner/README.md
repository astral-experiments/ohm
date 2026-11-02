# Full-workspace edit on a second runner

A fresh hosted Linux runner repeated the twelve-pair production comparison on the same landed uv edit. Each visit starts from an independently restored checked parent. The comparison adds #296 and #306 to matched Ohm −22 production sources with #318, using the same shipped Cargo. [Landed uv edit](https://github.com/astral-sh/uv/pull/20988) · [First runner](https://github.com/astral-experiments/ohm/tree/45b3dbb974f1c9fbce601daeb9296d6f85119e20/scripts/benchmark_results/uv-20988-production-root)

| Whole workspace command | Control | Combined patches | Paired median (99.365% interval) | Faster pairs |
| --- | ---: | ---: | ---: | ---: |
| Ordinary wall time | 6.524 s | 4.170 s | 1.564× (1.552–1.577×) | 12/12 |
| Userspace instructions | 62.199 B | 34.445 B | 1.806× (1.805–1.807×) | 12/12 |

The timing visits ran the ordinary uninstrumented Cargo command. Separate visits counted userspace instructions across Cargo and the processes it launched. The table uses the median of the twelve within-pair ratios and the second and eleventh sorted ratios. [Registered workflow](https://github.com/astral-experiments/ohm/blob/a08fbd2dc6330acc9a908657671a45611ab91478/.github/workflows/ci.yml) · [Original second run](https://github.com/astral-experiments/ohm/actions/runs/41393501771)

Run `python3 -I verify.py` to check the archived inputs with the Python standard library. To verify that its selected evidence matches the complete Actions ZIP, run `python3 -I verify.py --original /path/to/original.zip`. The complete ZIP has 702,276,200 bytes, SHA-256 `57f9bef5eb224bb70823c6d7df3f9611289f89b2af8d3c851f1486b9e0d778cd`.
