# Incremental ty_server test builds on Apple silicon

Rust #276 saved a full `zmij` compile on Ruff’s `ty_server` end-to-end test target. With incremental compilation enabled, the first unchanged build took 1.961 s on the parent and 1.898 s with the patch. The paired median speedup across 12 independently seeded pairs was 1.039×. Both builds already skipped Xcode’s linker on this repeat and still invoked one link-only rustc. [Rust #276](https://github.com/astral-experiments/ohm-rust/pull/276) · [Ruff edit](https://github.com/astral-sh/ruff/commit/aa9a1ff88aa83b3f01360ef5b3cb04b2be187206)

| Timed Cargo invocation | Parent median | Patched median | Median paired speedup | 96.1% interval |
| --- | ---: | ---: | ---: | ---: |
| Real edit | 4.570 s | 4.283 s | 1.030× | 0.917–1.146× |
| First unchanged build | 1.961 s | 1.898 s | 1.039× | 1.001–1.085× |
| Second unchanged build | 2.029 s | 1.869 s | 1.081× | 1.025–1.102× |
| Edit and first repeat timed together | 6.248 s | 6.039 s | 1.029× | 0.941–1.069× |

The primary endpoint was the first repeat. Its one-sided randomization test against a 2× speedup gave p = 1 across all 924 balanced allocations. Process-tree CPU on this endpoint fell from 2.560 to 2.425 seconds, a median paired improvement of 1.064×. Hardware instruction counts were unavailable. Median private allocation across the four endpoints was 2,434.3 MiB on the parent and 2,436.0 MiB with the patch. The two preceding pilot pairs are excluded. [Registered protocol](../../ty-developer-study.md) · [Original workflow](https://github.com/astral-experiments/ohm/actions/runs/41090114004)

Both arms used Cargo #293 at `735e1528ed` and ran `cargo +ohm test -p ty_server --test e2e --no-run --locked --offline -j4 --message-format=json`. The measured parent and child compiler subtrees match the public Rust #275 and #276 heads at `294dda2b65f1` and `1276de33b6b3`. Both compiled the real edit and linked the new e2e executable. Native readback covered all 96 timed products, 139 codegen objects per product and 19,620 signed pages per image. Each timed product matched its own empty build after verifying the invocation-specific Xcode object names. Every product listed the same 195 tests and passed both the existing and newly added cases. Both final independently empty builds passed the same checks. The clocks exclude test execution. [Original native archive](https://github.com/astral-experiments/ohm/actions/runs/41090114004/artifacts/13008850973) · [Independent readback](independent.json)

From this directory, recompute every interval and randomization test from the 96 original clock records and the separate system-time outputs.

```sh
python3 -IB verify.py
```

To compare every preserved clock record with its original ZIP member, download the workflow’s 372,144,130-byte artifact while available. The verifier checks its complete SHA-256 before comparing members.

```sh
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13008850973/zip > ty-confirmation.zip
python3 -IB verify.py --original ty-confirmation.zip
```

To rebuild the compilers and rerun the native inputs, pilots, twelve balanced pairs and clean references, dispatch the packaging workflow.

```sh
gh-auto workflow run ci.yml --repo astral-experiments/ohm --ref charlie/qa-apple-ty293-local-incremental
```
