# Full Ruff build after a branch return

The primary observation is hardware instructions retired by one ordinary command, including all children, after returning to a branch and editing a private AST comment.

```sh
cargo +ohm build -p ruff --bin ruff --locked --offline -j4 --message-format=json
```

The parent compiler is `393b4b05a4bfa3f531a36023846f86236a6b71a9` and the candidate is its child `df2c077a113a709ab379c8ec34e62c94c7513325`. Both use Cargo `761ea115605c34f11a1cd29afd68812c1e1359dd`, the original Wild binary, and `-Zohm-branch-cache=yes`. The latter is an opt-in. Each physical SDK occupies the same canonical location when active. Cargo may select different internal toolchain namespaces. Both output directories start empty for each clean reference and each separate history.

1. Build branch Y at historical Ruff `7b13f01ba1569887a25670820764b24c206da8e5` from empty. Switch to X at its parent `b5dba861cc38e3f7fb4524c9ceba3e01a474ea13` and build. Fast-forward X to Y without switching branches and build the real 169-file change.
2. Return to Y. Before running Cargo, replace `dead code warning` with `dead-code warning` in `crates/ruff_python_ast/src/nodes.rs`. Measure that build. Record the immediate unchanged repeat independently. The matched control makes the same edit while staying on X after otherwise identical training.
3. Introduce a real type error in the parser, require Cargo to exit 101 with E0308 at the edited line, restore the parser, and qualify the rebuilt CLI against the empty edited source. The invalid source and recovery follow the unchanged repeat in each primary history.

Two independent fresh Linux boots use opposite E/C order. Each replays the entire return history with the validated inherited user-instruction counter. All seven ordinary visits have hardware receipts. A separate run records actual installed executables and their arguments at Linux `PTRACE_EVENT_EXEC` stops for the real X→B edit, private comment, unchanged repeat, rejection and repair. The stay-X control records the comment and unchanged repeat. All cold and other training visits in these histories run ordinary Cargo with the same native product checks. Their physical compiler counts are unknown. The previous cold-project observer qualification passed one complete CLI build and refused two later cold runs with incomplete task lifecycles. A selected structural visit with an incomplete lifecycle refuses the pilot.

Read the complete commands and status, elapsed data, instruction count, enabled and running times, and independent kernel exec records. The study refuses uncalibrated counters or running time below 99.5% of enabled time. Cargo's reported dirty set is recorded separately from physical work. Structural and counter runs must agree on their output products and verdicts. Both roles have separate fresh reference builds of A, B, and edited B.

Each successful visit checks the 375 Cargo product records, runs the real CLI on lint, fix, recheck, formatting and malformed programs, and links and executes an external AST/parser client. The client must see 64 bytes at A and 56 at B. The opposite layout must produce E0308. Compare the complete CLI and client with the corresponding empty products. Compare executable sections and executable load segments between compiler roles, inventory allocated bytes across both output roots without double-counting hardlinks, and retain complete authored receipts and native reference bodies. Preserve differing native products for diagnosis. A verified behavior mismatch stops the worker.

Advance to a separately enrolled 12-boot confirmation only if **each** complete pilot has at least 2× fewer instructions at the preselected return-and-edit build, the candidate drops at least one full compiler without adding another or an extra real link there, and all native and hardware gates pass. Report the cold, training, unchanged, diagnostic, recovery, and storage costs alongside the primary result. Pilot boots cannot enter the confirmation. A speed claim requires a paired interval over independent new boots and the underlying skipped work. The small-library measurements used to design this study are separate from this full CLI endpoint.

Source run 41280518860 built the candidate and passed the compiler, cache-generation and pointer-identity controls. Its subsequent cross-compiler artifact comparison failed. Intake verifies that exact terminal history and reconstructs both native SDKs. The full CLI product checks run anew here.
