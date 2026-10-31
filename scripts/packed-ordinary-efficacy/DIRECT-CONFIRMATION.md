# Confirm the full Ruff workflow on the compiler in Rust #274

The packed compiler's first experiment and its two twelve-machine cohorts compare the cache switch on a compiler that also compresses object files. They cannot separate Rust #274 from that additional change. A separate exploratory experiment measures the original compiler, F, and its packed child, K. Run this independent confirmation only if both exploratory boots qualify and F with its branch cache disabled uses at least twice the instructions of F with its cache enabled on return-A, return-B and their sum. [Original compiler PR](https://github.com/astral-experiments/ohm-rust/pull/274) · [Two-boot attribution](https://github.com/astral-experiments/ohm/actions/runs/41219824213)

Use the source-qualified Rust compilers F `c6fe8ecda65452c105f85367a009af80cbb5efbc` and K `0afbeff303d3658bff52582d8f1a996d59e6c8ce`, strict Cargo `761ea115605c34f11a1cd29afd68812c1e1359dd` and stock Wild. Keep the attribution worker’s real 169-file Ruff revision switch, 505 locked dependencies, seven-visit histories, and literal `cargo +ohm build -p ruff --bin ruff --locked --offline -j4 --message-format=json`. Every arm starts with empty state. Replay each history both with and without the calibrated inherited retired-user-instruction counter. Require the original complete ELF and typed-client comparisons, Rust error and repair, native archive and generator controls, storage ledger, stable SDK identities, unchanged inputs and counter scheduling checks. [Source and measurement protocol](https://github.com/astral-experiments/ohm/blob/43111cc1644cc2fb89cc33eac321f3e2905edf1e/scripts/packed-ordinary-efficacy/ATTRIBUTION.md)

Enroll one independent six-machine cohort on a single immutable dispatch. Each machine runs all three arms. Use the orders below, once each. This balances the order and the immediate predecessor of each arm. Use no pilot outcomes in the estimate. Require six new distinct boot IDs, disjoint from the exploratory workers, the earlier excluded boots and the two packed confirmation cohorts. Retain a refusal and treat the direct endpoint as incomplete if an original observation cannot be qualified. No replacements or optional stopping.

| Position | First | Second | Third |
| --- | --- | --- | --- |
| 01 | Foff | Fon | Kon |
| 02 | Kon | Fon | Foff |
| 03 | Fon | Kon | Foff |
| 04 | Foff | Kon | Fon |
| 05 | Kon | Foff | Fon |
| 06 | Fon | Foff | Kon |

For each boot, divide Foff's sum of instructions across the two return commands by Fon's sum on those commands. Report the six paired ratios, their median and the exact distribution-free interval from the smallest to the largest ratio. It covers 96.875% for a continuous population median. A confirmed greater-than-two result requires all six ratios to strictly exceed two using integer arithmetic. With no ties, the one-sided sign probability under the median-at-two null is 1/64. Each of the six comparisons uses the same source-built compiler on both sides.

Disclose each return direction, the cold-through-return history, first switch, unchanged, deliberate error and repair. Separately report Fon versus Kon instructions and the signed additional target-plus-build allocated bytes on every phase, and the largest observed visit-end allocation for every arm. Present individual values and median with the same min-to-max intervals for these secondary effects. Treat them as descriptive. Describe added packing work, any space saved and its dependency on branch history. The interval between visits is unobserved. These six positions are separate from both packed-compiler cohorts. A benefit from branch reuse on F does not establish that also compressing object files accelerates Ruff.
