# Independent shipping benchmark audit

Passed 14,541 checks against the complete frozen matrix. All 312 commands were accepted, with 24 fresh cells, 312 successful runtime oracles, 24 clean-build format guards, 216 edit command-log checks, and 48 no-op identity checks. No observations were excluded or rerun.

Verified all 1,270 transferred files (523,408,877 bytes) against the remote SHA-256/size manifest and verified complete inventory coverage. Recomputed every published mean, paired range, count, and per-round comparison from raw rows. Independently checked CPU and child-RSS fields against GNU time receipts and tree-RSS peaks against monitor samples.

The measured compiler is Rust `e55e0485efc397741f4aaf861f1c74a281ac902f`, the measured fork linker is Wild `dba82ebe99d98adbfe6358215d456cdddb1877da`, and all four performance arms use installed Cargo `018a2b93409433dc5bc05c5fce838ae69e9bc396`. Cargo candidate `207626090e1fb9b405abd806a86c1b42bd2db5ff` has separate lifecycle validation; its executable is not the performance control. Later review heads are not relabeled as measured binaries. The measured candidate driver and linker hashes match the validated distribution receipts. Remote source heads stayed unchanged and clean; the original baseline driver matches the shipping baseline copy. Baseline and candidate bootstrap configurations are byte-identical.

The experiment uses eight jobs, line-table debug information, Ruff opt-level 1, and matched compiler builds without production PGO/BOLT. Each project has three fresh target rounds; each edit phase contains three sequential edits per round. The nine edits are not nine independent trials. Mode order is forward, reverse, forward. All arms use the same trust settings and whole-lane storage accounting.

## Archive tradeoff

Changes below are ratios of means; positive time means slower. Private means a library edit whose dependent binary used `-Zlink-only` in every recorded command log.

| Project | Reference | Clean | Direct edit | Private edit | Inline edit | Settled allocation |
|---|---|---:|---:|---:|---:|---:|
| uv | baseline | +0.98% | +8.52% | +1.16% | +3.88% | -18.97% |
| uv | standard | +0.52% | +9.51% | +1.10% | +1.83% | -18.97% |
| ruff | baseline | +2.03% | +9.59% | +0.75% | +7.41% | -13.91% |
| ruff | standard | +2.06% | +7.47% | -1.26% | -2.75% | -13.91% |

| Project | Baseline GiB | Standard GiB | External-store raw GiB | Self-contained archive GiB |
|---|---:|---:|---:|---:|
| uv | 3.4567 | 3.4568 | 2.3356 | 2.8010 |
| ruff | 2.5671 | 2.5671 | 1.9379 | 2.2100 |

The format merits further opt-in work as a storage tradeoff, not a speed or memory improvement. The measured compiler/linker bundle is not yet cleared for normal shipping: its default-off ordinary path has an unresolved performance concern, so disabling the format does not avoid all measured cost. It reduces settled allocation by about 19% on UV and 14% on Ruff, while direct edits cost approximately 0.22 s and 0.17 s against the existing baseline. Cold builds cost approximately 1.40 s and 2.52 s. The direct-edit slowdown against baseline is positive in all three Ruff rounds; against the matched ordinary candidate it is positive in all three UV rounds. Private-edit differences vary by round and remain small in aggregate.

The ordinary candidate already increases Ruff inline-edit time by 10.44% against baseline (round changes +17.74%, +13.53%, +0.51%). The archive is 2.75% faster than that matched candidate, but still 7.41% slower than the existing baseline. Reporting only the matched-candidate comparison would conceal this shipping cost. Eight of nine paired inline edits are slower in both wall and CPU, with a paired wall median of +9.98%; the three fresh round means are all positive. The mean changes are +0.277 s wall and +0.227 s CPU (+0.094 s user, +0.132 s system). Logs show the same two Ruff compiler invocations, library plus full binary compilation, without additional dependency rebuilds or Ruff interference flags. The matrix identifies the cost but does not isolate its compiler-versus-linker cause.

Source inspection of measured Rust e55e0485, compiler/rustc_codegen_ssa/src/back/link.rs:559–568, shows each static input archive is probed and then scanned for compact members whenever the compact options are off. The helper at lines 634–658 mmap/parses ordinary archive headers and member magic; this work is absent from baseline348339. This is a plausible additional cost on the ordinary path. It is not a demonstrated explanation of the inline result: ordinary direct/private edits increase only 1.97%/2.03%, and all binary links reach this path. A focused ordinary-path A/B or profile is needed before clearing the shipping concern. No new devbox benchmarks were performed during this review.

The external-store raw arm retains greater allocation savings: 32.44% on UV and 24.51% on Ruff versus the matched ordinary arm. Its timing is mixed, including direct-edit costs of 8.84% and 14.48%; its apparent advantages do not establish a generally faster default. Archive versus raw trades additional allocation for a self-contained artifact. The additional baseline-to-raw comparisons are retained in audit-shipping.json.

## Admission and measurement limits

There are 36 one-interval outside-CPU flags, all in UV. Thirty-five occur in the final monitor sample of compact-arm commands, consistent with the terminal-process ownership race demonstrated by the earlier instrumented prototype investigation. These records do not independently identify those processes. One baseline clean-build flag is interior to the run and measures 0.518 cores; it remains unattributed. Every row has fewer than the predeclared three-spike rejection threshold, and no unrelated compiler was recorded. The audit preserves all flags and their monitor positions; no retrospective exclusions or reclassification were applied.

Cold-build sampled tree RSS changes remain within about 3%. Short Ruff edit phases show large changes in sampled peaks, including increases against baseline, and the half-second process-tree sampler is sensitive to short-process overlap. These data do not support a memory-saving claim. Tree RSS sums process RSS, not PSS. Allocation is post-command ext4 allocation with inode deduplication across build, target, store, and scratch; it is not peak disk usage or unique CoW extents. The benchmark is offline and uninstrumented for peak disk.

Runtime oracle success checks the controlled semantic value plus --version and --help. Format guards apply to all 24 clean cells and record raw metadata, ordinary/compact object members, and store/manifests as appropriate. Standalone-copy, Cargo lifecycle, malformed-input, alignment, and distribution compatibility remain separately scoped correctness evidence, whose six admission receipts are hash-bound to the benchmark preflight.

To rerun this read-only audit after unpacking the evidence archive:

```sh
python3 audit/audit-shipping.py . --output /tmp/audit-shipping.json
```

The archive preserves the complete raw matrix and all audit inputs. The audit script does not invoke a compiler, edit a source tree, or alter recorded evidence.
