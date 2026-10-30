# Ron's share of an ordinary Ruff test check

Run one signed Ohm 1.99.0-21 Linux x86-64 Cargo, Rust, driver, standard library
and Wild on Ruff 93526150. The signed Cargo unit graphs select the package
that actually enables Insta's Ron feature, checking ty_server, ruff_db and
ty_project independently. No features are injected. The changed input is the
complete historical upstream change 32c5cd5d to the behavior and tests for
known module owners in ty_project. The experiment reverses it in a disposable
clone and authenticates both complete file states against upstream Git.

The measured command on the edited checkout and again on its first unchanged
visit is the normal native Cargo command:

```sh
cargo +ohm check -p ty_project --tests --locked --offline -j8 --message-format=json
```

An outside Linux ptrace observer follows actual exec/fork/clone events. It
opens one inherited hardware retired-user-instruction counter before the
real Rustup/Cargo first executes. It opens the second counter on the one
authenticated Rust compiler for `--crate-name ron` at the kernel post-exec
stop, before userspace and before its worker threads are created. Cargo
sees neither a compiler wrapper nor extra flags. The observer checks the
resolved physical executable and all NUL-delimited arguments. With both
counters enabled, seven native calibration topologies check an independently
sized sibling loop (whole count only) and the selected direct, fork,
grandchild, double branch, exec, and one/two-thread loops. Their known
instructions must match within 2%, with complete event coverage in every row.

If the unchanged check starts no Ron compiler or Ron accounts for less than
half of its whole-command instructions, acquisition stops. The maximum gain
from removing those instructions is whole / (whole - Ron). If Ron accounts
for at least half, the worker additionally checks a genuine source type
error and repair and takes a separate full Ron self-profile and compiler
phase report. That independent target, shared store, compiler wrapper and
profile are outside both measured commands. No elapsed speedup or product
change is enrolled.

The immutable first archive `primary.zip` is the original 309,996-byte
GitHub artifact from run 41139480769. Its digest is
`9e3a59e091c467c5139532dfb09cd8765eef343c938c0680e75da3ec2282ce3e`.
The first unchanged check crossed the threshold. Its subsequent strict repair
check failed because the new successful process printed the old E0308.
The follow-through uses the `recovery-and-profile` input, fresh output trees
and a separate profiling generation. It does not repeat either measured PMU
visit. It records Cargo's native child processes, overlay-free source bytes
and inode/timestamp, physical per-unit diagnostic caches, separate JSON and
human processes, sequential invalid variants and clean references for signed
-21, signed -21 with defaults off and signed -20. Its final Ron profile is
disjoint from the diagnostic sources and targets. All red verdicts are retained.
