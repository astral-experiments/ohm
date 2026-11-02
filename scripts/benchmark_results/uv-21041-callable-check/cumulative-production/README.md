# Cumulative production result on uv #21041

After the real edit, the production stack missed the preregistered 2× bare-wall threshold for ordinary `cargo check -p uv-client --locked --offline -j8`. Its matched factor was **1.4551×**, with 0/8 pairs strictly above 2×. The sum of the eight actual rustc processes fell by **46.12%**. [Actual edit](https://github.com/astral-sh/uv/pull/21041) · [Measured run](https://github.com/astral-experiments/ohm/actions/runs/41406359806)

The control was Ohm −22 sources with the #318 CTFE correction, commit `10d56274a988`. The treatment `f53496e2dd36` adds #296, #306 and callable trait receiver recovery. Both SDKs use the same production PGO+BOLT recipe and original signed −22 Cargo. The literal shipped compiler's warm/cold mismatch on this source motivated applying #318 to both arms. The marginal callable-only production study used a different control and an independent machine. [Marginal study](https://github.com/astral-experiments/ohm/actions/runs/41404703005)

| Endpoint | Control median | Candidate median | Paired speedup | Reduction | First four | Last four |
|---|---:|---:|---:|---:|---:|---:|
| Bare wall (s) | 1.842 | 1.266 | 1.4551× | 31.28% | 1.4354× | 1.4751× |
| Whole Cargo, billions of instructions | 17.835 | 9.882 | 1.8048× | 44.59% | 1.8048× | 1.8048× |
| All eight rustc processes, billions | 17.245 | 9.293 | 1.8558× | 46.12% | 1.8558× | 1.8559× |
| Terminal uv_client rustc, billions | 5.736 | 3.103 | 1.8486× | 45.90% | 1.8482× | 1.8489× |

The three visits per arm were separately restored. Bare wall used ordinary Cargo. The whole-command counter included Cargo descendants. Per-rustc events counted each of the eight kernel-identified Cargo-launched compiler processes and its threads. Each role used two independently warmed parents on one runner, with four matched pairs per hold. The preregistered one-sided sign family tested bare wall against 2.0 and summed rustc instructions against 1.25. Ties count as misses. The Holm-adjusted p-values were 1 and 0.0078125, respectively. Other endpoints are descriptive.

## Replay the retained measurements

```sh
python3 -ISB verify.py --self-test
python3 -ISB verify.py --json
python3 -ISB verify.py --self-test --original /path/to/original.zip
GH_AUTO_ACCOUNT=oss python3 -ISB verify.py --github-cli /home/dev-user/.local/bin/gh-auto
```

The first two commands run offline with Python 3.10 or later. The other two optionally check the complete original ZIP and GitHub service receipt. The verifier reopens all original arm orders, wall clocks, userspace counters, kernel process boundaries, native Cargo openings, actual compiler arguments and raw PMU words. It checks the four parent histories and the linked behavior, unit and metadata receipts. The two different compiler epochs were tested using eight natural native cache assertions, including warm reuse per compiler, and two genuine known-empty cache refusals.

The original Actions artifact `13123214141` is 34,873,735 bytes, SHA-256 `8fad7bbcaf6c98871ef35da167083f3d15700d7b70c78fb1a12e98921026d5f6`. This deterministic 134,548-byte subset has 594 exact original members. The full independent replay decoded 119 distinct rmeta files across 3,404 references. A new physical measurement requires the original private SDKs, signed Cargo, genuine uv source plus pinned registry closure and an independently calibrated runner for the workflow at `125cef4f90f572d8a8d19da42b0bc2b1fcae87a8`.
