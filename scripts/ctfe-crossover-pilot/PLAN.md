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

## Schema-2 contact and enrollment

The Git base is `5c651f1d38c629da2a75d5cac3588db0be8104d7`. The rejected two-boot kernel run was 41283234972. Both of its original incomplete terminal ledgers must still be refused by both parsers. The independently qualified, untraced screen was 41285793847 on `28fe14afcf485bc99e7bd9036d9b4f4bb990ce86`. It had two jobs, 124786714800 and 124786714903. The corresponding original ZIPs were 13075477706 (161,720,973 bytes, SHA-256 `ebbe8f31f3e680684b9cc05a93a9c85defb87f6d7a29b34dc7dd61ab718d5b77`) and 13075995840 (161,721,392 bytes, `439ceda73ab4a8bc23043024ce793e0b5f27c1cd6fa75b298e52d21d420b0d95`). Their original independent readback and summary are in `enrollment/`. All four of these boots and the earlier kernel calibration boots remain excluded.

Both new modes use only a manual dispatch, attempt one, the exact reviewed head and branch `charlie/qa-ctfe-v2-pilot-20261101`. Both require the registered Linux 7.1.4 x86-64 runner, reconstructed 81-file SDKs, the original enrolled source and effective-memory/disk guards. The checkout of the observer is `d4e1c4bac917a2de3218c13c50875b5c2d301a23` and the physical-role projector remains `5e91ed3974c0964a912fd38049946f647891dcb2`. The checked-out observer fixture sources, the retained acquired sources, the current compiler executable, the native closure and the raw output are independently compared on every host. The previous schema-1 cold contact is retained as historical evidence.

1. Dispatch `mode=contact` once with the reviewed head and empty contact inputs. One Eon worker runs independently empty A, B and edited B at fixed paths, then Y-B, X-A, X-B and comment. All seven Cargo commands are outside the PMU. X-B and comment alone have whole-process kernel tracing. A completed contact must verify both warm CLI and typed reader against their own clean executables and the complete 375-unit Cargo inventory. At least one of the two actual Ruff ledgers must identify a positive-output stock Wild image, its rustc ancestor and a distinct fork helper that inherits that image, with at least one parked peer, every terminal wait and a schema-2 footer. A local fixture with the same mechanism is retained only to test the reader.
2. Download the original contact ZIP and the official `run.json`, attempt-one `jobs.json`, and `artifacts.json`. From the enrolled checkout, use an independent checkout of the pinned observer and run:

   ```sh
   python3 -IB scripts/ctfe-crossover-pilot/contact_review.py offline \
       --run "$CONTACT_RUN" --head "$REVIEWED_HEAD" --official "$CONTACT_CATALOG" \
       --observer-source "$OBSERVER_CHECKOUT" "$CONTACT_ZIP" > contact-readback.json
   sha256sum "$CONTACT_ZIP" contact-readback.json
   ```

   The reader verifies the official job and archive identity, checks the full raw fixture suite and both ELF products, and records actual boot, tool, source and per-phase digests. It reads archived data without executing any archived binary. A refusal preserves the evidence and stops enrollment.
3. Only after this readback, dispatch `mode=full-pilot` on the same head, supplying `contact_run`, `contact_sha256` and `contact_readback_sha256`. Each worker first independently downloads and verifies that official contact and reproduces its certificate. It then qualifies its own observer on a fresh boot. The original two opposite orders, separate structural and measured acquisitions, three fresh references per role, stay-X, invalid/repair and decision rule above remain fixed. A measured phase containing any kernel/role evidence is refused. The stage cannot grant a third run or substitute a prior boot.
4. With the two new original ZIPs in position order, replay:

   ```sh
   python3 -IB scripts/ctfe-crossover-pilot/reopen.py \
       --run "$PILOT_RUN" --head "$REVIEWED_HEAD" --official "$PILOT_CATALOG" \
       --observer-source "$OBSERVER_CHECKOUT" --contact-run "$CONTACT_RUN" \
       --contact-official "$CONTACT_CATALOG" --contact-archive "$CONTACT_ZIP" \
       "$POSITION_01_ZIP" "$POSITION_02_ZIP"
   ```

The contact's resource and native verdicts are structural only. It contributes no instructions or measured samples. Any confirmation requires a new registration and fresh boots.

The first schema-2 contact on `ccc50f6df93ed41a55ccc3ff2e77c2f16fe77dce` stopped in the pinned SDK donor's Python import, before any native fixture, Cargo visit or counter ran. The successor keeps that original refusal and checks the pilot and donor module identities in a fresh process through the donor's first GitHub request, offline, before acquiring either compiler. [Original failed job](https://github.com/astral-experiments/ohm/actions/runs/41288606644/job/124794945295)
