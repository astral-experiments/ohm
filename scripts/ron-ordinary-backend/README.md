# Ron's native backend on the published Linux Ohm 1.99.0-24

Two independent fresh Linux workers run Ruff's actual five-file history and the default workspace command `cargo +ohm test --no-run --locked --offline -j4 --message-format=json`. The normal Cargo, rustc frontend, driver, LLVM and Wild are the binaries from the released Linux archive. The treatment is an experimental process supervisor and an in-process hook on the signed LLVM backend. Production rustc does not implement this hook.

The enrollment has one direct whole-command comparison on each boot, in opposite order. The parent side runs the unmodified Cargo. The treatment pays for its real loader, supervisor, input serialization, object/receipt validation and ordinary archive output. The inherited Linux user-instruction counter includes all child processes once. Separate kernel-observed runs establish actual compiler and linker identities, unchanged Ron arguments, CGU selection and library mappings. The observed whole-process guest IR from the separate -23 study is a different measurement.

Every experiment starts with an independent empty worktree target, shared build store and Cargo registry. Both historical source commits, all locked registry member bytes and the published 79-file SDK are checked. Each worker retains its original targets before building independent empty NEW at the same paths. The actual old native executable must fail its assertion with the edited source; edited, repaired and independently rebuilt executables must pass. Native consumers read the real Ron archive, emit E0308 on a deliberately invalid reader, and reproduce the original executable when repaired. A separate genuine invalid workspace edit must emit E0308 before a real repaired build. Complete native Ron inputs and selected executables are retained by content hash. The program records all observed runtime library names and generations on the unmodified kernel-census visit.

This diagnostic validates the front-end, rustc driver and LLVM under per-invocation private Linux read leases. Its three-file bill keeps the other installed runtime libraries fixed. A writable or custom runtime mapping requires its own authenticated generation before this approach could be used generally. File-name, timestamp and GNU build-ID tests alone cannot supply it. The complete separate runtime-generation study is an independent arm. The temporary staged source or result does not establish a performance gain or statistical significance for the full Cargo workflow.

A reviewer with job-dispatch access can repeat both arms by dispatching the checked-out immutable revision on its dedicated branch:

```sh
head=$(git rev-parse HEAD)
gh-auto workflow run ci.yml --repo astral-experiments/ohm --ref charlie/qa-ron-consumed-inputs-20261103 -f reviewed_head="$head"
```

The exact reference helper commit is in `registration.json`. LLVM public headers and the BLAKE3 reference C/assembly are bundled with member-by-member hashes in `components.json`. LLVM and BLAKE3 retain their respective upstream Apache-2.0-with-LLVM-exceptions and CC0/Apache-2.0 licensing.

The original two workers stopped before either treatment ran. Their first worktree snapshot was taken after a later same-source compiler had replaced the standalone Ron metadata at that path. The raw phase digests and native rosters are preserved in `refused-41719994394.json`. The new enrollment copies and validates each source-phase body before the next command.
