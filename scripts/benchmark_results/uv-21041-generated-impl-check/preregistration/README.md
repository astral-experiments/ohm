# Generated implementation identity after uv #21041

Before building a candidate, we measured the 97 type-checking and borrow-checking calls whose first recorded reason for running was one of two changed trait implementation lists. All 97 returned the same value before and after the uv edit. Their combined cost was **20.78% and 20.72% of terminal rustc instructions** in two independently prepared histories. These observations use the optimized stage-1 compiler with the external impl-directory change. [Landed uv edit](https://github.com/astral-sh/uv/pull/21041) · [Original stage-1 SDK](https://github.com/astral-experiments/ohm/actions/runs/41407590585)

| Instructions in the edited `uv_client` compiler | History 1 | History 2 |
| --- | ---: | ---: |
| Entire rustc | 5,090,327,773 | 5,088,167,855 |
| 50 affected type checks | 313,351,049 | 313,168,418 |
| 47 affected borrow checks | 744,175,402 | 741,061,850 |
| Union of those calls | 1,057,526,451 | 1,054,230,268 |

The 97 intervals had zero overlap. Eleven type-checking calls also had other direct inputs with changed values. Thirteen borrow-checking calls depended on other queries that separately failed an incremental check and later returned the same value. A changed compiler must establish how much work it can actually avoid.

The first identity we considered, rustc’s existing expansion hash, changed between incremental and nonincremental compilation at the same source path and revision. All three observed implementation and method identities on the existing compiler agreed across modes. The prospective correctness gate requires preserving that property. [Cross-mode observations](cross-mode-original.json)

The registered comparison uses normal `cargo check -p uv-client --locked --offline -j8`, counts each of the eight compiler processes, and includes cold compilation plus the older `cargo build -p uv-cli` regression on uv #20992. Hardware confirmation requires eight fresh pairs. [Scoring and controls](protocol.json) · [Additional cross-mode gate](cross-mode-gate.json)

Run `python3 -ISB verify.py` to match every recorded provider interval to the original enrollment, recompute the instruction costs from the two captures, and verify the expansion-hash falsifier. The compressed Callgrind files retain both complete original graphs.
