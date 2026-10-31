# Source and native qualification on the Ruff AST musl build

The parent reproduced three full rustcs and no link on both ordinary repeated library builds. Its build emitted hard dep-info markers for `zmij`, `compact_str` and `ruff_python_ast`. The test harness also reran those rustcs and the real target GNU linker. The test root did not itself emit a hard marker. The 183-file SDK and complete clean program and test ELF hashes are in `parent.json`. [Original parent run](https://github.com/astral-experiments/ohm/actions/runs/41166655409)

The four-path `candidate.patch` is the exact full-index diff from reviewed Rust `adea62b64bb86ad18946457dfb59f36b2d8fcab4` to `d52336754e01c65758f0be7335b191be47baf02f`. `source.json` pins its separate matched bootstrap tree, unchanged library tree, and all four resulting Git blob IDs. Both Rust compilers use ordinary Cargo #301, the same stock Wild on the GNU host, matching rustdoc, and true `x86_64-unknown-linux-musl` libraries. The previous host plus AArch64 member registry contains 119 files. The current source builder adds rustdoc and 63 musl members, independently builds the candidate standard libraries and requires every complete file except the Rust driver to match. Six C startup/runtime files come from Rust 1.99.0's verified official musl package. Raw source bootstrap logs include the old compiler failing the registered new test and its child passing the same fixture. `subjects.py` retains any different component hashes before rejecting the transfer.

The source job creates one shared SDK archive and its alternate driver. Two older Cargo binaries are separate read-only compatibility fixtures. Every receiver checks the source run, attempt, branch, source job, archive digest, manifest digest and the original SHA-256/size/mode of every installed file. Two separate workers run normal Ruff old/edit/unchanged/invalid/repair/clean commands and run a separately compiled musl visitor against the resulting library. The edit is exactly the upstream two-file Ruff #27404 change applied to pinned Ruff `93526150`. The normal `test --lib --no-run` path is a structural secondary. Kernel execution and raw rustc dep-info are collected separately from an unwrapped ordinary build history. The physical target ELF and visitor output must agree with the corresponding independent clean. The original real-file assembler fixture and its native provider guard are retained. Two more workers run a genuine v2 dependency owning an unbundled archive with actual provider mutation, compiler changes and both older Cargo readers in private and shared storage. They verify physical linker and archive use. A residual hard root is reported separately from native correctness and does not widen the admitted template grammar.

The read-only Actions workflow takes a single manual dispatch on its dedicated QA branch.

```sh
gh-auto workflow run ci.yml --repo astral-experiments/ohm --ref charlie/qa-musl-ast-reviewed-compiler
```

After all five jobs succeed, retrieve an immutable source transfer for separate measurements. Supply the full commit and official successful run ID. The following bootstrap authority must be present in `GH_TOKEN` on a hosted worker.

```sh
python3 -IB scripts/ohm-musl-ast-pair/lookup.py "$SOURCE_RUN" "$SOURCE_HEAD" >> "$GITHUB_ENV"
# On the next Actions step, using the emitted five values:
python3 -IB scripts/ohm-musl-ast-pair/restore.py P
```

The transfer artifact lasts six days. The original recorded driver and Cargo are also required by this historical reconstruction; see `../ohm-musl-ast/sdk.py` and `subjects.py` for the bound GitHub inputs and their identities. This workflow supplies behavior and mechanism evidence. Its separate workers do not form a paired timing estimate.

The first source qualification exposed E0282 in the newly added `rmake.rs` before its parent behavioral assertion could execute. `failed-fixture-41168023795.json` seals the original failure. The fixture-only successor adds one explicit `bool` type. All compiled Rust product sources and the native qualification criteria match the original registration. [Original failed source qualification](https://github.com/astral-experiments/ohm/actions/runs/41168023795)
