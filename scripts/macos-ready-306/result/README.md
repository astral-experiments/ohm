# The macOS ready-test timeout on Cargo #306

The original macOS CI job passed 4,384 integration tests and failed
`ohm_ready_tests::uses_current_runtime_inputs_and_ignores_disabled_binaries`.
The test's synthetic `z` compiler wrapper had already finished invoking
rustc. It waited 15 seconds for `a`'s test to write `control/a-timing`,
then panicked. The signed Cargo source parent had passed all 4,385 in its
historical official macOS run. Both original full logs are retained here.
[Original #306 job](https://github.com/astral-experiments/ohm-cargo/actions/runs/41146481154/job/124372664295) · [Original #294 job](https://github.com/astral-experiments/ohm-cargo/actions/runs/40988650504/job/123845475750)

Each targeted study rebuilt the actual Cargo executable and integration suite
from a complete verified source tree with Rust 1.99.0 on Darwin 24.6 arm64.
The production revisions were `2d44bd4a` and `c7f394c8`. The integration
test's full source had SHA-256
`03d2fa196a80c0af1c67ece2fb2cf952e15c60caae0419e115fd5a2459fd2aa5`
on both. A fresh libtest process recreated the fixture on each visit.

| Named visits | Parent | #306 |
|---|---:|---:|
| First unmodified cohort | 8/8 | 7/8 |
| Unmodified visits in the observer cohort | 4/4 | 4/4 |
| Extra queue logging in the test driver | 10/10 | 10/10 |
| Queue logging and a 40–600 ms delay in the edited build-script compiler wrapper | 10/10 | 10/10 |
| Unmodified late stack-sampling cohort | 60/60 | 60/60 |

In the failing targeted visit, only `slow-active` existed after Cargo returned.
The generated `a` build-script output still contained the zero-byte seed and
the new `OUT_DIR/value` file was absent. In successful visits the actual tests
saw the new application binary, new build-script environment and new output
file. The disabled binary contains an intentional compiler error, so any
unexpected compilation of it would also have failed the visit.
All unmodified attempts together returned 72/72 on the parent and 71/72 on
#306. The 20 additional observed visits per revision use a separately changed
test driver and the same physical production Cargo as that installation.

In the last 60 visits per arm, the observer polled for the fixture's own
marker. It would take a native stack sample after an already active wrapper
had waited for 2.15 seconds. No visit reached that trigger. A delayed build
script also completed the test when its new file appeared about 600 ms after
`z` had finished its real compiler. These observations do not identify what
stopped progress in the original 15-second interval.

The #306 code changes are in the shared garbage collector, plus a Linux-only
direct dependency. The fixture calls Cargo build and test. Source review
found no call to the modified collector in those commands. The optional
ready-test scheduler is disabled for `cargo test --no-run`. The logged
failure is in the later command that both compiles and runs tests. Its rare
timeout remains unexplained. No parent visit reproduced it.
[Ready-test gating](https://github.com/astral-experiments/ohm-cargo/blob/c7f394c8c9aaef1272c621ff11d77dcf569ed94b/src/ops/cargo_test/mod.rs#L70-L90) · [Fixture](https://github.com/astral-experiments/ohm-cargo/blob/c7f394c8c9aaef1272c621ff11d77dcf569ed94b/tests/testsuite/ohm_ready_tests.rs#L266-L310)

Run `python3 -IB verify.py | cmp - summary.json` from this directory. It
reopens all six exact Actions ZIPs, reads physical compiler identities,
verifies every enrolled target's single native test verdict, checks the
runtime markers, and reopens both original full CI logs.
[First cohort](https://github.com/astral-experiments/ohm/actions/runs/41147398265) · [Queue observer and ordering controls](https://github.com/astral-experiments/ohm/actions/runs/41147809007) · [Late-sampling cohort](https://github.com/astral-experiments/ohm/actions/runs/41148226731)

## Exact-source macOS CI repeat

GitHub rejected the attempt to rerun only original job 124372664295
with HTTP 403 because the containing workflow still had Linux jobs in its
queue. The supplemental job checked out #306 directly. Its source tree is
identical to the original CI merge checkout. It selected the original
macOS matrix row and retained every command from the original job, including
its installed-toolchain controls. The fresh ordinary suite passed all 403
Cargo library tests and 4,385 integration tests. The exact ready test
printed `ok`. The 421 ignored integration tests remain recorded. The original
failure and the later passing run are separate observations.
[Exact-source macOS suite](https://github.com/astral-experiments/ohm-cargo/actions/runs/41149336548/job/124381841038)

The CI command's legacy `profiles::ohm_default_debuginfo` selector returned
zero. The six actual Clippy and worktree tests each ran once and passed on
its pinned Ohm 1.98.0-9 and separately on signed Ohm 1.99.0-21.
A separate current-toolchain run physically listed and ran both real
`profile_settings` names and all six worktree tests individually. Each of
those eight returned exactly one pass against #306 with the authenticated
signed macOS release. Its 42,929-byte Actions artifact SHA-256 is
`27e0c0740571fff0cca0d1b14886826bdd41e4f9ef48dc35281f713cae9263ee`.
Cargo #307 owns the workflow selector fix.
[Eight current-toolchain tests](https://github.com/astral-experiments/ohm/actions/runs/41149581243/job/124382639563) · [Selector fix](https://github.com/astral-experiments/ohm-cargo/pull/307)
