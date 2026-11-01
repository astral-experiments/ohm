# A one-file Ruff parser edit on signed GNU Ohm

Measure the instructions used by these two ordinary, fixed-branch applications of the same code edit. One native Linux worker runs both commands separately. This is a baseline diagnostic. There is no candidate compiler or speedup ratio.

```sh
cargo +ohm build -p ruff --bin ruff --locked --offline -j4 --message-format=json
cargo +ohm test -p ruff_python_parser --test fixtures --no-run --locked --offline -j4 --message-format=json
```

The signed GNU `1.99.0-22` archive is 359,852,703 B, SHA-256 `bcf21a3bcdfedd7174ef56ae17a5511fa5b2b6a0afff4b725bed6c5da50194d7`. The inherited receiver verifies all 79 required executable/library members (553,526,772 B) and the `rustup` selection. Cargo is `ed0ae15d22da9a0af9afb3d0fdeb4ceb8a71b770`, Rust `008a21ac0d750dc9a1c18b7959d7e7984c03d887`, and stock Wild `0d633580…`. Both commands use default release behavior, without wrapper, opt-in solver flags, trusted proc-macro/native helpers or a linker override. Ruff's locked 505 crates are authenticated before the first compile. This workload does not test that Cargo version's separately known transitive GNU provider bug.

## Source and behavior

The production hunk is the exact `git diff --full-index` for `crates/ruff_python_parser/src/parser/statement.rs` in Ruff `abee0da3f2ccf12f322ac50817b621d32753f860` relative to `691b60a3f3bc0c28318ee866747da8c7f0af3d3a`. The actual upstream commit also adds a Python fixture and its AST snapshot. Our application is to unchanged Ruff B `7b13f01ba1569887a25670820764b24c206da8e5` on one ordinary local branch. The production source changes from `ed90735b…` to `b107023b…`. A genuine `git apply --check` and `git apply` change just this file, without staging or changing HEAD. The immutable B Git tree, physical index, watched refs, full tracked/untracked status and production source bytes are checked before and after every actual Cargo command. [Upstream PR](https://github.com/astral-sh/ruff/pull/29761)

The target case is `try: work()` followed by `except ValueError: raise; report()`. Before the edit the actual native CLI must diagnose `Expected an expression` in line 2, columns 25–26; after the edit it must exit 0 with no diagnostics. Each CLI also runs three parser controls (valid existing bare raise, explicit exception before a semicolon, malformed `raise from`), the existing genuine CLI checks and the compiled 56-byte `Expr` client, including its deliberately wrong 64-byte alternative. The ELF that Cargo exposes must be byte-identical to its state’s independent empty executable.

The normal parser test build emits 152 compiler artifacts, with 19 additional build-script executions in its 171-unit signed Cargo plan. Its real ELF must execute all 557 original named fixtures successfully. Only after Cargo exits, two exclusive-create writes install the original #29761 input and `.snap` (SHA-256 `ef5231e6…` and `00bcbfaa…`). The actual native listing must gain exactly `inline_ok::bare_raise_before_semicolon.py`. Running that unique case must return 101 with the exact syntax error before and pass its real upstream snapshot afterwards. The reference and warm runs use the same checked bytes. The harness receives `INSTA_WORKSPACE_ROOT` and `INSTA_UPDATE=no` only at test execution, so it resolves the registered B snapshots even when the repository’s pinned Cargo 1.98 is absent. Both added files are inode- and byte-checked before removal. No test fixture is present during any Cargo invocation. The original upstream Linux Debug and Release jobs independently passed this case on their own merge revision. [Upstream run](https://github.com/astral-sh/ruff/actions/runs/40539690882)

## Histories and attribution

Each command has the same six histories at identical absolute source, active SDK, target and shared-build paths. Every new history begins with both output roots empty. The source retains B and its one Git index for the entire experiment.

| History | Actual Cargo visits |
| --- | --- |
| Empty before | Original B |
| Empty after | Edited B |
| Empty invalid | Edited B plus one real Rust type error |
| Plain 1 | Original B, then measured edit |
| Inventory | Original B, separately traced edit, ordinary unchanged, genuine E0308, repair, reverse-to-B |
| Plain 2 | Original B, then measured edit |

The prospective record is 26 Cargo product invocations, plus two unscored `--unit-graph` requests. Only four are measured. Every plain window is the inherited `enable_on_exec` userspace hardware instruction counter on the child that runs `cargo +ohm …` and its descendants, including Rust, linker and helpers. Calibration, observer, hashing, tests, fixture staging, checks and collectors run outside that process tree. All four counters must be positive, succeed and have exactly equal enabled and running durations. Report both absolute counts and their spread separately by workload. A spread above 2% is reported as such. The preregistration establishes no optimization comparison.

Only each inventory edit uses the original positive-kernel-`exec` collector, in its counter-disabled `topology` mode. Its executable and `watch.c` are byte-identical to the signed-default first-A registration. A single checked Python callback seam dispatches the existing complete lifecycle decoder in topology-only mode. It requires all tasks reaped, all selected raw count rows zero, unique physical signed Cargo/rustc/Wild identities, a full real `ruff_python_parser` compile and one real stock Wild write to the actual final executable. Each physical compiler must match the Cargo target, features, output name and inode. A full compile supplies its Rust source. A checked link-only executable supplies the sibling `.rlink` as its sole input after the edition flag and an explicit `-Z link-only`. Hash the same regular recipe before and after, including device, inode, length, mode, mtime and ctime. GCC, collect2 and stock Wild must all name the actual Cargo executable inode. Reopen the public executable’s whole SHA and six stat fields immediately around its native verdict, and compare with the structural output and reference ELF. Only previously observed signed query argv may appear outside the compiler owners.

Signed Cargo can report a local library as non-fresh and skip its compiler when a dependency’s public API is unchanged. For each such unit require its two registered local `.rlib` and `.rmeta` outputs. Hash both whole files through checked regular FDs before and after the structural visit. Each must preserve device, inode, length, mode and content. Record both timestamps, which Cargo may advance. A missing owner for any other sort of unit refuses. The 35 local library roles in the original CLI needed 318,942,735 bytes per read. All these reads and native checks run outside measured windows. Compare every Cargo artifact, feature, profile and path against its own clean and planned graph; compare the exact dirty set for both plain edits with its independently traced edit. Missing or refused native evidence prevents terminal admission. The unchanged, error and repair client runs have no primary counters.

Require one true `E0308` on the single bad Rust line, identical to an independently empty invalid build, and byte-for-byte native, executable-load, source and verdict parity on repair, reverse and unchanged. Preserve complete compressed reference ELFs, raw Cargo/stdout/stderr, test verdicts, false/fresh units, and both traced physical histories. Any warm/clean `.rodata` or GNU build-ID discrepancy refuses literal equality and retains the difference. The independent reader never executes archived code.

## Enrollment and cost

One 16-vCPU GNU worker selects four distinct physical cores. Before downloading the signed SDK, entry needs 25 GiB free and 16 GiB effective available memory. At least 24 GiB workspace must remain after installation. Runtime floors are 4 GiB workspace, 6 GiB receipt volume and 8 GiB effective memory. The two roles run sequentially with only one active pair of output roots. Prior CLI builds occupied around 2.0–2.5 GB; the local parser rehearsal produced 25,763,160/25,763,168-byte native harnesses in a hard-capped 1,152 MiB temporary filesystem. The earlier CLI ELFs were about 147.5 MB each. Plan roughly 20–50 minutes and 85–170 MB of compressed evidence, with a 90-minute refusal and a 768 MiB accepted ZIP-member envelope. No hardware time or instruction estimate is taken from the local parser contact.

Manual admission requires attempt 1, the reviewed SHA, an empty artifact catalog, and independently read prior boot descriptors in this shape:

```json
{"six":[{"job":0,"artifact":0,"digest":"sha256:…","boot":"…"}],"first":{"run":0,"job":0,"artifact":0,"digest":"sha256:…","boot":"…"}}
```

The real `six` list has six positions from original `41336398017`. A distinct already-completed signed-default first-A worker must have the exact `5cc8582f…` source/job and its own original artifact. The exact previous input is in `excluded-hosts.json`. Also exclude the two subsequent refused originals, one-file 41349575789/124976652509 and first-A replay 41349209691/124975532927. All nine jobs must precede this worker. Its boot UUID, runner ID and runner name must differ from every one. Recheck each replay’s branch, head, terminal state and archive identity/digest/size in the official catalog and offline.

The first one-file run reached the real parser compile, saved CLI relink and Wild output. Its 375-unit graph reported 16 dirty, only two with physical rustc owners. The old parser required a Rust source operand for both. The archive lacks precommand file hashes, a completed parser history and the remaining native comparisons. It is an unscored regression fixture. Exactly four `calibration/nested-plain-{0,1,2,3}/exec.tsv` must be empty; all other calibration and native trace files must be nonempty and pass the original decoder.

A structural readback failure retains the actual raw trace, before/after facts and precise exception. Both native histories continue and the worker refuses before emitting an accepted result. The two previous refusals stay distinct from this opportunity.

For independent replay, check out collector `8a659140df8ab27fd6a8cc61f5eb38717b3f8bbc` and contract `42ab30fd5e6bcdcf908df81de9baac65ca64fbf9`. `terminal.json` holds the actual original `run`, `job` and `artifact` API objects. The package source check, tests and replay are:

```sh
sha256sum --strict --check --status scripts/ruff-one-file-parser/SHA256SUMS
python3 -IB scripts/ruff-one-file-parser/test_onefile.py "$COLLECTOR" "$CONTRACT"
python3 -IB scripts/ruff-one-file-parser/test_saved_link.py "$COLLECTOR" "$CONTRACT"
python3 -IB scripts/ruff-one-file-parser/verify.py --zip official.zip --catalog terminal.json --previous previous-boots.json --head "$REVIEWED_HEAD" --collector "$COLLECTOR" --contract "$CONTRACT"
```
