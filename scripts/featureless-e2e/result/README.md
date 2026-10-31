# Strict Cargo and #293 on the ordinary signed GNU e2e build

Both workers passed the native and instruction-observer gates. Open Cargo #293 already skipped the e2e frontend on the ordinary feature-free command and preserved its genuine GNU link. Removing all non-linker work inside the strict e2e compiler would have saved at most **9.68%** of this command. On #293 the remaining upper bound was **0.20%**. Each bound comes from the same worker's inherited counters and adjacent untraced whole-command readings. [Registered protocol](https://github.com/astral-experiments/ohm/tree/69c21b3ecf8510871c346f751c60866e302708d5/scripts/featureless-e2e) · [Actions run 41163189762](https://github.com/astral-experiments/ohm/actions/runs/41163189762)

| User instructions, billions | Strict, first | Strict, second | #293, first | #293, second |
|---|---:|---:|---:|---:|
| Whole ordinary command under observation | 19.749 | 19.690 | 17.880 | 17.877 |
| Executed Unicode generator | 12.152 | 12.158 | 12.160 | 12.159 |
| Entire e2e rustc tree | 5.195 | 5.129 | 3.320 | 3.320 |
| Its GCC, collect2 and Wild descendants | 3.285 | 3.284 | 3.286 | 3.285 |
| Residual e2e compiler work | 1.910 | 1.845 | 0.0346 | 0.0346 |
| Within-worker upper speedup from removing that residual | 1.1071× | 1.1034× | 1.00194× | 1.00194× |

The two receivers ran on separate machines. Both ordinary unchanged traces under strict Cargo ran three full compilers and two Wild links. The strict Cargo logs reported the synthetic native-link recheck path. Cargo #293 ran two full compilers, a link-only e2e rustc, and two Wild links. Its two logging-only visits preserved `StaleDepFingerprint { unit: UnitIndex(285) }` and explicitly reported codegen reuse. Both workers retained 139 e2e native objects and the same workspace marker text `untrusted compile-time inputs`. Both had all 149 installed signed SDK file paths, including rustdoc and the complete native standard library. The traced/sham absolute whole-counter deviations had medians of 2.07% and 1.84% respectively, with maxima of 4.38% and 3.68%. The calibrated nested outer-minus-driver deltas were 20,000,140 and 20,000,139 against 20,000,000 expected.

The real eight-file notebook edit and its restoration each invoked 15 rustcs, including a full e2e compile, plus two native Wild links on both receivers. Both independent original builds and restored histories returned the same complete 210,121,432-byte e2e program, SHA-256 `4c096fc597fbbf7197923c2f5ab68bbb24cef0788b56a785b67c84ae4aedf6ef`. Each independently clean reversed build and corresponding history returned the same 210,108,760-byte ELF, SHA-256 `f264ce3adf1824ba8c8e6b9b08a6212bcfa9a75061feac0d905c28ea5f324daa`. The actual inventory went from 200 tests to 199 and back to 200. The `notebook::cells_after_cell_magic` test passed whenever present, along with the always-present `notebook::inlay_hints_range_past_end_of_cell` control. The normal graph contained 277 typed Cargo units. The independent generator accounted for 61.54–61.75% or 68.01% of the two workers' traced totals respectively.

## Offline audit

The compact archive holds exactly the 536 original inputs read by the verifier, deduplicated to 203 logical byte strings. It contains kernel ancestry and native argv, hardware counts, separate Cargo INFO logs, raw depfiles and markers, executable section/segment receipts, and actual native case/list outputs. The original ZIPs contain 548 and 539 members. Both complete original archives were read, hashed and checked, including members outside the verifier projection.

From this directory, run the following with Python 3.11+ and zstd. It requires no GitHub access and reproduces the original qualification JSON with SHA-256 `7e2bc4c6d0b1cf22f8133322701dda35d1750a790e95b59cd480003be06534e7`.

```sh
python3 -IB verify.py --output /tmp/featureless-e2e-result.json
```

The archive records the original compressed and decompressed digests. The replay recovered all 536 original member encodings byte for byte with the qualifying zlib. Another zlib implementation can encode the same authenticated logical bytes differently. To additionally verify the received outer archive bytes and original member encodings, pass both ZIPs using `--strict-zip PATH --pr293-zip PATH`.

| Receiver | Original Actions artifact | ZIP size | ZIP SHA-256 |
|---|---|---:|---|
| 761ea115 | [13027159509](https://github.com/astral-experiments/ohm/actions/runs/41163189762/artifacts/13027159509) | 5,465,057 | `fdd3fa987709c0c5431a1e51a89f626f18fad83fb07e75f100a1309ce720c429` |
| 735e1528 | [13027883805](https://github.com/astral-experiments/ohm/actions/runs/41163189762/artifacts/13027883805) | 5,459,241 | `289f54cfca5066dd8fa6132a335aef12615b297102298b8c86bb3552be6da0dc` |
