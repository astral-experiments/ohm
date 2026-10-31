# Does Cargo #293 reuse native e2e codegen on the ordinary signed GNU build?

Two independent x86-64 Linux workers each run one existing Cargo on an identical complete signed Ohm -21 Rust compiler, standard library, rustdoc and stock Wild. The strict worker consumes the 761ea115 repair ELF. The other consumes 735e1528 from [Cargo #293](https://github.com/astral-experiments/ohm-cargo/pull/293). Both receiver binaries come from earlier authenticated native builds. Verify the GitHub run, artifact and binary digests in the acquisition scripts. The original -21 Cargo is retained for custody. Only `bin/cargo` changes in each complete installation. Save every installed member with its hash, mode, inode and timestamps, plus actual rustc/rustdoc/Cargo versions.

Each worker has eight pinned cores on a 16-core Namespace worker, requests at least 70 GiB initially free, and has a 50-minute cap. The earlier four-cold-build e2e qualification finished in about six minutes per worker. This is a descriptive structural comparison. Its two workers run different receivers, so their whole-command counts do not establish a performance ratio.

## Source and verdicts

The ordinary command is `cargo +ohm test --no-run -p ty_server --test e2e --locked --offline -j8 --message-format=json`. It sets no Cargo feature switches, wrappers, trust overrides, extra Rust flags or loader interposition. Both workers use the same exposed SDK, workspace, registry and build paths. Enroll Ruff 93526150df078af7dd8fc4226cdcc469539d2001 with the original 498 locked registry archives. The checked-in eight-file notebook change is the literal 13,226-byte upstream patch with SHA-256 f5a3c6085bb0e90335c5f1686a0eb9c61e1456aa5d5808381a2deea304b3650d. Verify both complete Git trees before the first command.

1. From empty, build original, run two ordinary unchanged commands under a kernel exec observer, reverse the real notebook edit, repeat, restore, repeat. Require Wild to produce the returned e2e file on both changed visits. Save device/inode-resolved rustc, Cargo and linker argv. Read the actual native libtest inventory and execute exactly its enrolled notebook and inlay-hints tests outside every counted command.
2. Independently discard both owned target and shared roots, then compile each source state afresh, with a fresh copied authenticated registry. Every returned native program in its own source state must match its own independent clean entire ELF, native test list and named success. Reversing the patch must remove only `notebook::cells_after_cell_magic` and change the ELF. Restoration must return exactly the old binary. Any byte mismatch remains a failed gate. Preserve section and segment digests plus both complete compressed divergent products.
3. Reuse only the separate empty-original history for two unmeasured repeat visits with Cargo compiler INFO and fingerprint DEBUG. Retain the complete logs, encoded Cargo fingerprint/dep-info, rustc depfile, native recipe, SHA-256 by native object, and actual workspace seed/deny marker bytes. The current receiver may overwrite the earlier dirty reason internally. Only claim a specific predicate when the log actually exposes it. A deny marker on a complete installation establishes a trust state, independent of the reason it was written.

## Within-worker instruction attribution

A fourth empty history runs the same command with the ordinary kernel exec census. Enroll its physical signed rustc, stock Wild, system GCC, compiled generator and actual e2e output. Then run five unchanged commands in order S T S T S. S counts the whole process tree with no ptrace or logging. T uses the previously tested native inherited hardware counter and separately counts the actual e2e compiler family, Unicode generator family, e2e GCC linker-driver family and e2e Wild family, from their stopped execs through all threads/children. Observe unaltered Cargo from rustup under each mode. Verify the real e2e → GCC → collect2 → Wild ancestry, actual kernel image identities, output pathname and source or saved recipe. Compare each emitted program and its native verdicts with the independent original. Named tests run outside the observer.

The e2e compiler count minus its whole GCC family is a generous upper bound on removable compiler work when the native link stays. It includes preparation still needed by link-only rustc. Record the disjoint generator separately. Nested counters include one another and must never be summed. First require a known-instruction calibration with separately copied real executables, a four-process nested/sibling topology, and an inner thread. Two zero/work pairs must recover whole, all four scopes and the derived outer-minus-driver delta within 2%. Every admitted PMU event is a positive, nonmultiplexed userspace retired-instruction count. Across the four trace-to-neighbor deviations require median below 3% and maximum below 8%. Missing roles, inaccessible hardware, a different native topology, or a failed observer guard leave that cost unqualified. An observer error after a known Cargo false verdict remains a semantic failure; the one optional direct same-state recheck keeps its original evidence.

Require both semantic panels before interpreting an opportunity. Only infer a sub-2× ceiling if the maximum removable fraction is below one half of the smaller of the traced total and both ordinary neighboring counts on each trace. A larger fraction would warrant separate investigation. No release or statistical performance qualification follows from this comparison.

## Replay

Dispatch the dedicated QA ref only after the frozen source is approved. It runs precisely the two roles above. Its current ELF inputs were last verified available October 31. The strict original ZIP expires November 1 at 00:40 UTC, the #293 ZIP November 2 at 14:59 UTC. Results retain provenance for any later source rebuild.

After downloading both original Actions artifacts by ID and verifying GitHub's archive SHA-256, extract them into `strict/` and `pr293/`. From this worktree, with `run` set to the Actions run ID and `head` to its immutable QA head, run

```sh
python3 -IB scripts/featureless-e2e/reopen.py strict pr293 --run "$run" --head "$head" --output result.json
```

The reader reopens own native binaries' receipts, scopes, complete raw Cargo logs, direct input proofs, and whole-command flanks. It compares actual test inventories and named verdicts across both workers, while keeping costs separate. Full SDK binaries live in the signed release and native Cargo build artifacts.
