# Does the rebuilt Ruff CLI use the edited file classifier?

Two manual GNU workers each run the ordinary 375-unit command on one authenticated compiler. Eon uses Ohm Rust 393b4b05a4bfa3f531a36023846f86236a6b71a9 and Con uses df2c077a113a709ab379c8ec34e62c94c7513325. Both use strict Cargo 761ea115605c34f11a1cd29afd68812c1e1359dd, the same stock GNU Wild binary (SHA-256 0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5), and the explicit branch-cache opt-in. This experiment establishes native correctness; it collects no hardware counters or timing endpoint.

```sh
cargo +ohm build -p ruff --bin ruff --locked --offline -j4 --message-format=json
```

Each worker reconstructs two disjoint 81-file SDKs from the previous source artifacts, then activates its assigned SDK at one canonical path. Cargo's target and explicit shared build directories stay at the same distinct absolute paths throughout. Both jobs use fresh independent runner roots. The inherited intake authenticates the successful native source step in run 41280518860, its artifacts and the subsequent failed historical Ruff gate separately. The prior pilot and its workflow checksum are reopened from the frozen 5c651f1d checkout. The new workflow has its own manifest. The Actions read token is scoped to source acquisition.

The checkout begins on Ruff Y at 7b13f01ba1569887a25670820764b24c206da8e5 (B). It switches to X at the direct parent b5dba861cc38e3f7fb4524c9ceba3e01a474ea13 (A), then fast-forwards X to B across the original 169 changed files. The Cargo.lock and all 505 fetched registry archive contents are checked. Every successful build must emit the same complete graph of 375 typed Cargo units, an executable reporting the expected commit, and an independently compiled client consuming the actual AST and parser rlibs. The client reports Expr=64 at A, Expr=56 at B, and a contradictory client must fail with E0308.

| Visit | Required source and observations |
| --- | --- |
| Y-B | Empty canonical target and build directories. All 375 units must be non-fresh. Retain the complete original B CLI and typed reader. |
| X-A, X-B | Original branch switch and 169-file fast-forward, with compiled and executed native outcomes at both revisions. X-B must reproduce the original B output. |
| edit | Return to Y, preserving its watched ref identity. Change only `"pyi" => Self::Stub,` to `"pyi" => Self::Python,` in crates/ruff_python_ast/src/lib.rs. Require a physical full AST compiler and the unique stock Wild invocation writing Cargo's Ruff binary. |
| repeat | Same checkout, AST, parser and watched physical ref identities as edit. Run the ordinary command and every native control again. |
| invalid, repair | Add the registered ill-typed line to the parser while keeping the edited classifier. Require exit 101 and E0308 at that line; permit the ordinary compiler's failed-session grace period. Restore only the parser and require the correct successful edited CLI and client. |
| revert | Restore the original classifier bytes. Require a physical CLI link, the original whole ELF and all original native verdicts. |
| empty-edit | Discard only the two owned output roots, recreate them at the identical physical paths, and apply exactly the same semantic edit again. All 375 units must be non-fresh. |

The classifier source SHA-256 changes from 712c897ad642964bb8526dcb13d97bb1917add11cb627e894b738c6f4affa428 to cb988a3c7709f0a5cb184ceb5776f67f527f0c458d8b5111f9595d448f12f06b. All successful visits run the CLI on the actual input `def f() -> None:\n    pass\n`. Ordinary `.pyi` gives one PYI009 with its original location and safe fix, then exit 0 and an empty JSON array after the edit, then the original diagnostic after reverting. Explicit `--extension qno:pyi` always gives PYI009. Ordinary `.py`, `.qno`, and explicit `--extension pyi:python` stay clean. The separate version, E711, f-string, format, invalid syntax and native reader controls run at every successful visit.

Only edit and revert use the already enrolled stock strace exec observer. The physical signed-Wild path and SHA must match the selected SDK. Its real `-o` file and the single executable named by Cargo must have the same device/inode, mode, length, timestamps and complete SHA-256. The raw argv, exit, source files, Cargo messages, all five CLI results and compressed full ELF bytes are retained. Other visits have unknown physical compiler/link counts. The worker keeps partials on a source, observer, resource or correctness failure.

Admission requires each warm edited, repeated and repaired CLI and reader to match its own independent empty edited build byte-for-byte. The return and revert must match the original B build. The edited CLI must differ from both its original B body and its original verdict. Across the two jobs, require the same source and native verdicts and executable sections/loads for both programs; report both whole-file hashes. A mismatch stays visible. The verifier can run only after it authenticates the terminal workflow/jobs and both ZIPs from read-only official metadata. It reopens the stored ELF bodies, checks every native stream, and re-executes each distinct CLI as a sealed anonymous file from a private directory. It binds the original diagnostic file name to that actual directory when replaying it.

```sh
python3 -IB scripts/ctfe-cli-semantic/test.py
python3 -IB scripts/ctfe-cli-semantic/test.py --repo /path/to/ruff --old-cli /path/to/41243597545-01-13058834903.zip --old-link /path/to/41200174886-02-13043111933.zip
python3 -IB scripts/ctfe-cli-semantic/read.py --official /path/to/catalog --run "$RUN" --head "$REVIEWED_SHA" Eon.zip Con.zip
```

Use the attempt-1 Actions run, its jobs and artifact catalogs as run.json, jobs.json and artifacts.json. The historical ELF preflight executes the genuine A and B CLIs from original 13058834903, checks 10 native verdicts and rejects original B when presented as the edited CLI. The second historical archive supplies the real compiler/Wild argv for the ordinary GNU edit. Only a new native hosted pair can qualify the edited 375-unit workflow.

[Historical native-source qualification](https://github.com/astral-experiments/ohm/actions/runs/41280518860) · [Original full-CLI ELF used for the oracle](https://github.com/astral-experiments/ohm/actions/runs/41243597545)
