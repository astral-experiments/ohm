# Ruff literal-table correctness

These runs compare the compiler from Ohm Rust #353 (`6c2874a0b6a0`) with the follow-on that packs large constant character and tuple tables (`06fe634feaa3`). The #353 source PR head adds its run-make test to the measured compiler. Both Linux SDKs were built from the signed `-24` source base with the same bootstrap and signed Cargo and Wild.

The archive contains 137 original entries, 276,214,039 bytes before deduplication and compression. Its SHA-256 is `53e5d428424877cbfa35608cb100ee587d889d56c78cb018bc3be1077f240036`. The independent reader checks all underlying bytes and decodes original target objects and Cargo messages. On Linux x86-64 it can also run the 18 distinct native executables.

```sh
python3 -IB scripts/ruff-normalization-price/evidence/target-layout/verify.py --run-native
```

## Target layout

There are 11 exported object symbols on each of x86-64 little endian and s390x big endian. The reader decodes each ELF symbol and compares each row with its typed values. All 22 comparisons matched the preceding compiler, including the `(u16, u32, u16)` whose source fields have physical offsets 4, 0 and 6. The extended compiler packed five fixtures. Padded tuples, an attributed row, a suffixed row, an out-of-range literal under an allowance, a cast and the short table took the preceding path. The run-make regression exercised eight lowering sites, native values, static addresses, two invalid builds and a repaired build on empty incremental storage.

## Cross-crate uses

The Cargo client uses the exported table to determine a const generic length, a type alias, a named constant pattern and a runtime lookup. A 3-to-5 edit rejected an independently declared three-element client array twice. A nested producer value of 65,536 rejected two separate builds with the original `u16` diagnostic. The old, repaired, downgraded and second-upgrade executables passed their value and pattern checks. After repair and after each compiler transition the complete executable matched its independent empty build on the same SDK.

Separate eligible 1,024-row tuple arrays exercise named, distinct, offset, aligned, mutable and anonymous allocation identity. Both compilers agreed on the observer's runtime values and its compile-time `guaranteed_eq` checks. Repeated invalid clients failed and repaired native executables matched clean builds.

## Ruff dependency upgrade

After Ruff moved `unicode-normalization` from 0.1.24 to 0.1.25, the dependency's complete built `.rmeta` went from 1,720,649 to 733,953 bytes. Its `.rlib` grew from 209,648 to 209,700 bytes. Each was byte-identical to its arm's independent empty build. The combined target and shared build directories retained 407,349,119 versus 405,377,867 logical bytes after the edit. The larger downstream Ruff parser had ten differing lines in its 293-line decoded crate record after worktree history versus an empty build on the signed source baseline, #353, and the extended compiler alike. All three showed the same affected dependency rows. The separate hardware study runs the real parser and all Unicode scalars against the old, edited, repaired and independently empty builds. [Ruff change](https://github.com/astral-sh/ruff/pull/21229) · [Two-order hardware pilot](https://github.com/astral-experiments/ohm/actions/runs/41755609477)

## Ruff generator holdout

Ruff's genuine RNG migration emits another 13,490 `(u16,u16)` entries and 40,470 `char` entries in its perfect hash function. All three compilers received the same three generated sources. For the complete edited `unicode_names2` rustc, one local Callgrind run per compiler measured 9,489,390,493 simulated instructions on the signed source baseline, 5,830,046,582 with #353 and 4,744,397,650 with the extended lowering. These are software counts for one compiler invocation. The archive retains the original profiles, Cargo rosters and compiler invocations. [Ruff change](https://github.com/astral-sh/ruff/pull/29261)
