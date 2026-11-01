# Darwin Diesel failure in RC22 instrumented rustc

This one-host QA workflow rebuilds the Apple Silicon PGO instrumented compiler from the original release inputs and runs the nine original training benchmarks together. It captures Diesel's original failed incremental directory before retrying anything. The original RC22 job retained its diagnostic and source record. Its instrumented compiler and graph were not uploaded. A reconstruction can establish whether the failure recurs with the same sources, build configuration, collector and target. Historical byte-for-byte compiler identity is unknown. [Original macOS release build](https://github.com/astral-experiments/ohm/actions/runs/41256793646/job/124701560586)

**Source and workload.** The workflow checks the original integrated Rust commit `1bc7b35699479d5899a2935d79392b7bdaf7497d`, Cargo `4591cf45cc10abb19d2456c40b99606e08167f29`, Clippy and rustfmt, the original release bootstrap and checked-in opt-dist shell. The aligned Rust commit `c5178286c2661c22ef4ed304d7213589483548ee` has the identical complete Git tree `bbfe1faca29784b74e01830873eae7d8f27b52f0`. The qualification rebuilds the original commit to preserve its reported version. The packaging job pins LLVM 23.1.2, targets `aarch64-apple-darwin`, and uses the original release script and opt-dist environment. The primary runner passes the original pinned rustc-perf `0a054b0ead56e41a4584bfab6fdc1a5fad2aedc3` all nine benchmarks, three profiles and all four scenarios with four concurrent benchmarks. It leaves Cargo, rustc, the collector and its temporary directory handling untouched. The collector labels its benchmark group AArch64UnknownLinuxGnu on this host. The actual native compiler host and its captured command select Darwin.

**Positive stopping condition.** The original opt-dist runner writes an explicit success line after the complete Rust profile has been merged. The supervisor requires the original collector command, all nine unique completed benchmark names and all nine positions before stopping its private release process group. This saves the later independent rustdoc and distribution work. A natural error is allowed to exit normally. A step records the complete initial log even if the source, stage, profile or expected error checks refuse.

**Original capture.** The collector uses `ManuallyDrop<TempDir>` at `collector/src/compile/benchmark/mod.rs:424`. A failing `IncrPatched` compile returns early at line 527, before its successful cleanup. The Eprintln runner writes the actual child stderr to `eprintln`. The post-failure step reads the exact recorded Cargo cwd and 49-argument stage2 rustc invocation, including the native output, proc-macro library and incremental paths. It checks the actual patched source and the stage2 decoding backtrace. Artifact `diesel-pgo-first-original` retains the entire failed tempdir, physical metadata and hardlink groups, every captured dep graph and the real command. The tar and graph SHA-256s are checked against the live originals before the first artifact is uploaded. If the prior session was already absent, the original workspace still uploads and the replay gate refuses. The runner never harvests an unrelated tempdir.

**Separate same-binary diagnostics.** After original custody, the job tests the actual stage2 Mach-O sections, executes the compiler and Cargo, checks the emitted counters with the matching LLVM, and reopens a portable SDK. Its own rustc must resolve its own std and compile a small metadata crate. The exact recorded Diesel rustc then reads verified copies at the same visible path, using A/B source with the previous state and A/B source with no incremental directory. It separately runs the original unmodified collector for Diesel Opt alone, with a new temporary state and the same compiler and Cargo. Direct replay reconstructs the recorded opt-dist environment and both explicit rustc-perf stamps. Cargo did not export a complete snapshot of the failed child environment. Only the original and fresh genuine collector runs have Cargo's full environment. A per-SHA eager-header and deeper graph decoder runs on the original escrowed bytes. A deeper edge error can precede the exact node-header assertion in the native reader.

**Budget and receipts.** The original instrumented bootstrap took 46m54s and the full Rust training attempt took 15m58s. Its release-build step lasted 66m01s and recorded 56.53 GiB free after the failure. One macos-15 host has a 180-minute bound, including acquisition, two verified archives, a focused collector capped at 25 minutes, and up to four four-minute direct reads. The standard release cleanup enforces its own minimum; the additional source-time floor is 40 GiB. Escrow keeps 4 GiB free, plus the prospective copy size. Its caps are 2 GiB of distinct input bytes per workspace and 3 GiB per portable SDK. The same-path reader reuses one APFS clone at a time. All three artifacts expire after seven days. Reopen their official size and SHA before retaining them. The final step preserves a reproduced primary failure as a failed job regardless of any successful retry. If the original passes, the captured failed graph does not exist and no saved-graph replay is claimed.

## Reviewer commands

Run the source and subprocess tests on an ordinary Linux or Darwin checkout.

```sh
(cd scripts/darwin-pgo-diesel && shasum -a 256 --check SHA256SUMS && python3 -IB test_local.py)
```

To inspect an individually saved raw native graph, supply its independently verified hash and bytes. The tool exits nonzero when the recorded contents are rejected. For raw inputs it uses a read-only memory map.

```sh
python3 -B scripts/darwin-pgo-diesel/eager_header.py /path/to/original-graphs/GRAPH_SHA --sha256 GRAPH_SHA
```

`exercise_capture.py` also exercises the main worker's capture and both decoders end-to-end with the actual original Darwin log, unmodified pinned Diesel source, and an authentic small GNU incremental file. The valid file and its source-identified one-bit intervention are bound by hash. The separate control produced one exactly located duplicate index. No compiler is launched by this test. Replace the arguments with local custody paths.

```sh
python3 -IB scripts/darwin-pgo-diesel/exercise_capture.py TMP_PARENT DIESEL_SOURCE GNU_GRAPH ORIGINAL_APPLE_LOG NEW_RESULT_JSON
```

The only dispatchable path is manual workflow `ci.yml` on the dedicated QA ref `charlie/qa-rc22-pgo-diesel-forensics-20261101`. Supply the complete locally reviewed QA commit as `reviewed_head`; the workflow requires attempt one, the same GitHub head, a one-commit difference from prior QA and only the scoped workflow/harness changes. It uses read-only repository permissions and never signs or publishes a release. Check overlapping optimized Darwin jobs before deciding whether to dispatch.
