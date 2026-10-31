# Can skipping the compiler frontend halve this Ruff build?

On the first unchanged `cargo +ohm build -p ruff_annotate_snippets --examples`, work inside the twelve rustcs but outside their native links accounted for **50.71% and 50.70%** of userspace instructions. Removing every one of those instructions for free would just exceed 2× on both independent hosts. A real implementation could spend at most **12.17 million and 11.87 million instructions** in total across twelve outputs and still reach 2×. We measured the existing stack only. There is no demonstrated product speedup. [Frozen plan](../PLAN.md) · [Hosted run](https://github.com/astral-experiments/ohm/actions/runs/41175267642)

| Native Linux worker | Historical Ruff edit | First unchanged build | Edit + first unchanged |
|---|---:|---:|---:|
| 01, attributed then plain | 1.15874–1.15876× | 2.02897–2.02905× | 1.25798–1.25801× |
| 02, plain then attributed | 1.15884–1.15889× | 2.02825–2.02849× | 1.25798–1.25804× |

These ranges use the two measured whole-command denominators with the same optimistically removable instructions. They describe sensitivity to whole-command observation. Each worker used a separate fresh installation for its two observations at the same canonical path, changing the order on the second worker. Both saw 55 Cargo units. The real edit compiled the library and twelve examples, with twelve native links. The library alone cost 5.688 and 5.690 billion instructions. The immediate unchanged command compiled the twelve examples, with twelve native links. [Full counts and argument order](result.json)

| First unchanged build, millions of instructions | Worker 01 | Worker 02 |
|---|---:|---:|
| Whole, independent untraced | 1,705.146 | 1,704.755 |
| Whole, with attribution | 1,705.209 | 1,704.552 |
| Twelve complete rustc subtrees | 1,510.099 | 1,509.539 |
| Twelve cc subtrees including the actual Wild link | 645.320 | 645.291 |
| Wild alone, already within cc | 610.584 | 610.557 |
| Rustc minus cc, optimistic removable work | 864.779 | 864.248 |
| Cargo and all other work outside those rustcs | 195.109 | 195.013 |

The native trace separately closed 347 Linux tasks and 50 execs on each repeat. Each actual example linked through cc, collect2 and the released Wild with a forked worker. The measurement uses the twelve disjoint `rustc − cc` differences. On the edit it excludes the library compile. Both workers passed all 28 established whole-command controls and eight additional nested controls, with two independently known positive instruction counts and idle controls.

Both installations on each worker applied the same Ruff renderer fix. All twelve example ELFs changed after the edit, and the new ones matched the independent empty rebuild byte-for-byte. The twelve example programs produced the same output before and after the fix. Ruff’s real `multiple_insertions` regression test exercises the changed behavior. It observed the expected renderer panic on old source and correct rendering on fixed source. The signed −21 rustc, host standard library, rustdoc and stock Wild were retained, with the source-built #301 Cargo. A separately retained invalid same-stat native-provider control made this exact workflow fail at the native linker. [Source and tool custody](../README.md)

GitHub reports both jobs red. Their acquisitions finished, and then the offline check sorted a map before reconstructing the ordered list of concurrently executed examples. Replaying the original verifier reproduces that final assertion failure on each receipt. The corrected reader recovers the actual exec order from the kernel ledger and compares the complete original ordered report, including every instruction integer. Swapping two rows or changing a real cc event by one instruction makes the reader reject the data. The original pre-enrollment sysfs error is archived separately. [Original host-read failure](../prior-host-read/README.md) · [Original measurement workflow](https://github.com/astral-experiments/ohm/tree/5f3fcc6d826788835fd11eb668444d3b50236961/scripts/gnu-example-ceiling) · [Both original ZIP identities](official.json)

From this directory, run the following with Python 3.11 or newer and zstd.

```sh
sha256sum --strict --check SHA256SUMS
python3 -IB reopen.py
```

The 467,832-byte compressed capsule contains every regular file from both original ZIPs. It stores the two 656-member directory mappings and 626 distinct streams by SHA-256. The reader independently reconstructs the compiler, native linker and whole-command counters, typed outputs, ancestry, sample order and cross-boot gates. To also compare each original ZIP byte-for-byte by its GitHub digest and its members against the bundled capsule, supply the directory containing `gnu-ruff-example-ceiling-01.zip` and `gnu-ruff-example-ceiling-02.zip` with `--originals DIR`. [Worker 01](https://github.com/astral-experiments/ohm/actions/runs/41175267642/artifacts/13032524238) · [Worker 02](https://github.com/astral-experiments/ohm/actions/runs/41175267642/artifacts/13032825645)
