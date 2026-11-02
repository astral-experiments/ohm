# Ruff workspace option edit on signed GNU

This one-host screen measures a real edit to the documentation and example that Ruff prints for `lint.per-file-ignores`. The registered command builds only the workspace library and the dependencies Cargo resolves for it.

```sh
cargo +ohm build -p ruff_workspace --lib --locked --offline -j4 --message-format=json
```

The old Ruff commit is `3c77dcc2a5c04fc0c54ce95cd51068734015f3e0` and its direct child is `088b7b5f77fcb05994fd2a17cbc940cd9edb341a`. The harness checks the exact parent, trees and blobs, then applies the two tracked files as a working-tree edit while retaining the same checkout and output paths. Cargo's target and build directories are separate. The published GNU −22 asset is 698533704, SHA-256 `bcf21a3bcdfedd7174ef56ae17a5511fa5b2b6a0afff4b725bed6c5da50194d7`, with Rust `008a21ac0d750dc9a1c18b7959d7e7984c03d887` and Cargo `ed0ae15d22da9a0af9afb3d0fdeb4ceb8a71b770`. The worker validates all 79 installed files. [Ruff edit](https://github.com/astral-sh/ruff/pull/28106)

## Measurement and controls

The first history measures whole-command user instructions on the old empty build, real edit, unchanged repeat, inserted workspace E0308, repaired source and adverse revert. Each primary window contains only the normal Cargo command and its descendants. The calibrated event must run for the full enabled interval and return the expected status, including Cargo's 101 on the invalid source. Source edits, snapshots and client runs take place outside each window.

Five further histories reuse the absolute paths after independently emptying both owned output directories. They provide a pass-through observer, a workspace-only save-temps observer, an ordinary clean new build, a save-temps clean new build, and an ordinary edit with per-compiler instruction accounting. The two observer edit counts are each reported relative to the primary count. The per-compiler counter gives a separate upper bound if the entire workspace rustc invocation were free. No compiler treatment or speedup is measured.

The physical recorder derives from `ba324a8a8c5e0e57d12ca8a9a0d0031ea9aa6056`. Its only source change restricts the save-temps predicate to the workspace library. In both diagnostic modes every actual signed rustc command is retained, including probes and all other crates. The reader compares matching codegen-unit names across the actual newly emitted pre-LLVM bytes, the old and new retained native archive members and the independent clean builds. If inputs or names differ, it reports those modules separately. The optional save-temps diagnostic supplies no flags to ordinary measurements.

After a successful visit a separate client binds Cargo's concrete workspace and option-metadata archives. The native program prints the changed field and an unchanged sibling, and exits 2 with no output for a missing option. The checker compares exact historical bytes after each visit and independently executes the retained ELFs. A second typed client must fail with E0308. The source compiler must diagnose the intentionally invalid declaration in the workspace itself. Cargo's complete successful artifact multiset must match the all-dependencies unit graph. Both input revisions have the same graph.

The job admits four physical cores on one fresh 16-core GNU runner. It requires 24 GiB of initial work space and 16 GiB of effective memory. During the worker it guards 4 GiB free in the work filesystem, 6 GiB for receipts and 8 GiB effective memory. It caps compressed codegen originals at 2 GiB and native clients at 300 MiB. The complete manual job has a 90-minute deadline. Any refused control keeps the available raw report.

## Independent replay

Use the exact reviewed QA checkout, `collector` at `8a659140df8ab27fd6a8cc61f5eb38717b3f8bbc` and `contract` at `42ab30fd5e6bcdcf908df81de9baac65ca64fbf9`. Authenticate the official terminal job and original artifact ZIP digest against GitHub before replay. On a GNU x86-64 host with an executable temporary filesystem run the following from the QA checkout.

```sh
python3 -IB scripts/ruff-workspace-option-edit/setup.py sources
python3 -IB scripts/ruff-workspace-option-edit/reopen.py ORIGINAL.zip COLLECTOR_CHECKOUT CONTRACT_CHECKOUT REVIEWED_QA_HEAD --execute
```

The small signed fixture exercises the two real field literals, the upstream metadata API, the promoted root archive, three diagnostic modes and a true empty new build. A completed full-workspace report is required for a statement about this edit's whole-command cost.
