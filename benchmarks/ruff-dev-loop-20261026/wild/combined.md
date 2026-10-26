# Four Cargo changes and the ThinLTO Wild package

We compared the four Cargo changes and the ThinLTO Wild package together against an identically optimized release-14 Cargo parent and the released Wild executable. Both arms used the same published release-14 rustc and driver library. We checked their inode, change time and size before and after every Cargo invocation. This is an independent measurement of both packages together.

| Ruff workspace command     | Parent median whole-command instructions | Combined median whole-command instructions | Paired reduction (95% CI) |
| -------------------------- | ---------------------------------------: | -----------------------------------------: | ------------------------: |
| `cargo +ohm build`         |                                   5.576B |                                     5.447B |    2.32% (2.30% to 2.34%) |
| `cargo +ohm test --no-run` |                                   4.668B |                                     4.597B |    1.50% (1.37% to 1.64%) |

We used the same one-byte Ruff CLI and formatter-test edits and whole-command instruction accounting as the separate Wild study. The build rebuilt only the CLI among 501 units, and the test build rebuilt only the formatter integration test among 619 units. Each of 12 pairs per command uses identical source bytes. Independent randomization seeds were 2026102628 for build and 2026102629 for test. Each edit direction occurred in six blocks. Paired log ratios, exact two-sided randomization tests and stratified bootstrap intervals use the analysis described in the Wild study. [Per-process counts and output digests](combined.csv) · [Wild package comparison](README.md)

Build favored the combined suite in 12/12 pairs, with a two-sided p of 0.000488. The test build favored it in 12/12 pairs, with a two-sided p of 0.000488.

The Cargo parent at `461a3d1007ecc997a6d86c7d75e8b518575c8d90` and the four-change stack used the same release PGO training profile. Their executable SHA-256 digests were `211465de4b9e4589da2be06871acd9304dd3b94c849c1304f723484cb4f71dfc` and `9346a13cd66ec30b9bc369f12bb305ff943eb6ec9ff15f47646ab74f784f8e60`. The combined source diff's SHA-256 is `02c3cb466d2f7a9c08c1f867f59f52485b4b81f02f19c73ee847da6a777292bd`. [Exact combined Cargo changes](https://github.com/astral-sh/ohm-cargo/blob/a9f8eccf2cc63a7f648ea262a66a8a8ed4a737ad/benchmarks/ruff-dev-loop-20261026/cargo-stack/four.patch) · [Cargo PGO inputs and build instructions](https://github.com/astral-sh/ohm-cargo/blob/a9f8eccf2cc63a7f648ea262a66a8a8ed4a737ad/benchmarks/ruff-dev-loop-20261026/cargo-stack/README.md)

| Cargo draft                                             | Measured head                              |
| ------------------------------------------------------- | ------------------------------------------ |
| [#242](https://github.com/astral-sh/ohm-cargo/pull/242) | `f98a9e825516553171c88a85d55bfff7b0f9b748` |
| [#243](https://github.com/astral-sh/ohm-cargo/pull/243) | `184e50b93316db9478f82eae2e35b789ba6ab1e9` |
| [#244](https://github.com/astral-sh/ohm-cargo/pull/244) | `e0c8d5d08ce852965ecb7f06e3cff97651892acb` |
| [#245](https://github.com/astral-sh/ohm-cargo/pull/245) | `28c2b64e0936098e900c01d864fb0a026233e917` |

Use the private release-14 toolchain, independent Ruff worktrees and build-directory settings in the Wild study. Supply the Cargo binaries built from the linked parent and four-change source. The runner copies both programs into private, stable per-worktree paths. [Whole-command replay](measure.py)

```sh
CARGO_TARGET_DIR="$RUN/build-target" taskset -c "$CPUS" python3 "$EVIDENCE/measure.py" \
  build "$RUFF_BUILD" "$RUN/combined-build" "parent=$SHIPPED" "stack=$RUN/thin/wild" \
  --cargo "parent=$PARENT_CARGO" --cargo "stack=$STACK_CARGO" --seed 2026102628
CARGO_TARGET_DIR="$RUN/test-target" taskset -c "$CPUS" python3 "$EVIDENCE/measure.py" \
  test "$RUFF_TEST" "$RUN/combined-test" "parent=$SHIPPED" "stack=$RUN/thin/wild" \
  --cargo "parent=$PARENT_CARGO" --cargo "stack=$STACK_CARGO" --seed 2026102629
python3 "$EVIDENCE/analyze.py" "$EVIDENCE/combined.csv" parent stack
```
