# Installed checks for the final 1.99.0-23 native distributions

This manual workflow uses the unchanged platform and assembly archives from the first attempt of [41351902967](https://github.com/astral-experiments/ohm/actions/runs/41351902967). That workflow owns the actual compiler builds, PGO, assembly, and stock smoke on GNU/Linux and Apple Silicon. The supplemental workflow has read-only permissions and one ordinary runner per platform. Each job has a 75-minute ceiling.

The native builder and assembler must both be Ohm `e408863e7ba61fac3e054a580e149dbf4c89f582`. The tested manifest SHA-256 is `ef76f8eb83ea78d7ab3bf272bb3aea0ba2729bd3f626af0faf4842f0c2b51c65`. It pins Rust `a3fc6da13921586bc374586dee00883e9210aecd`, Cargo `159be68484a7f8cb05debf82bee89e594b7f19b6`, Clippy `5b5d9fb377e21872c83ed1598f9ffee1420c7b39`, and rustfmt `59e87b3b3eb731560e1c3a1da4319af04bda5483`. The receiver checks the four source trees, all six successful native workflow jobs, and the upload log, official size and SHA-256 for each artifact. The two small source ZIPs and the native build logs bind the 27 Check/Debug/Opt rows, nine completed benchmarks, and six executed PGO tools to the native SDKs. The earlier provider `41348186330` used a different manifest and rustfmt. Its originals remain a separate historical comparison.

The large files stay on the hosted workers. Each downloads its own published Actions ZIP once, plus the small three-file global ZIP. Each verifies the seven assembled files, uses the actual embedded installer, runs both native toolchains through their real rustup launchers, and compares candidate actor bytes with its distribution. The Linux worker keeps its original ZIP for both target-specific tests on that same runner. The Apple worker never downloads the Linux distribution. The signed -22 predecessor comes from its independent public release. Both consumers retain original test argv, stdout, stderr, native results and partial reports if a check refuses.

Both hosts exercise worktree registration/remap, interactive ready-tests, the genuine Ruff documentation diamond and nominal type, graph rejection/recovery, trait projection and incremental format migration. The host-specific GNU probes also distinguish changed, missing and malformed native inputs from the admitted unchanged archive. Both hosts run the literal-path and concurrent-registration installer check and the Cargo install collision/reinstall histories. The published test suite is `4fe6d1c0`, legacy fixtures are `46258d8b`. Its runtime registration contains the new compiler/Cargo, exact source fixture blobs, and numeric epoch 26655.

The producer's stock smoke already covers rustfmt, Clippy, rust-analyzer, default compiler flags, a host executable, wasm, and an ordinary seeded worktree. Its relink script also checks a declared archive shadow from an earlier watched directory. This supplemental workflow omits the generic stock smoke. It retains the paired native fixture because it saves the repaired executables, runs them, and compares declared, marked and malformed states across the two separately installed toolchains.

Both native regression matrices compare the candidate with the publicly shipped predecessor, Rust `008a21ac0d750dc9a1c18b7959d7e7984c03d887` and Cargo `ed0ae15d22da9a0af9afb3d0fdeb4ceb8a71b770`. Protected run `41303825957` produced the tagged release. Its GNU tar is release asset `698533704` (359,852,703 bytes, SHA-256 `bcf21a3bcdfedd7174ef56ae17a5511fa5b2b6a0afff4b725bed6c5da50194d7`), and its Apple tar is `698533709` (295,001,987 bytes, SHA-256 `4106b90c07ae918a6960e13ef16eb9536ebf8ff39ff04abbdf0c320ebf86d684`). Each runner reopens and hashes its own original release tar, verifies installed native tool bytes, and checks the actual compiler and Cargo revisions. [Published −22 release](https://github.com/astral-experiments/ohm/releases/tag/ohm-1.99.0-22)

On the GNU runner, the cross fixture checks the only changed compiler file since the previous Rust pin. Its independent source and native archive checks cover 31 AArch64 GNU assembly cases and 13 x86-64 musl cases. It uses the installed Rust compiler, Cargo, LLVM and rust-lld, and needs Linux clang with its AArch64 backend and Ubuntu's signed `qemu-user` package. The freestanding AArch64 ELF executes in QEMU; the musl x86-64 ELF executes natively. No target standard library or registry download is required. The GNU source keeps every original assembly body and uses a source-matched minicore scaffold. The separate stock smoke builds the host executable and a wasm32 module and checks its binary header.

The extra cross-target harness was rehearsed locally on an **unshipped release candidate**, Rust `556a8364f1485a03be31b1a50c250d63198a943d` and Cargo `8269d772aa1ef02e5efaa331dfb40eb55d71f719`. Its 27.20 seconds, 52 direct compiler invocations, and 30 Cargo visits describe that rehearsal. The installed-only workflow runs those target-specific checks on the original candidate GNU package from `41351902967`. [Earlier release-candidate run](https://github.com/astral-experiments/ohm/actions/runs/41237680370)

## Resource limits

The hosted receiver checks at least 10 GiB before downloading, retains a 4 GiB transfer reserve, and caps each platform ZIP at 1,200 MiB. The signed predecessor installer independently requires more than 10 GiB free when it starts. The installer concurrency test admits the observed capacity only if two copies of the actual native installed size plus compressed archive fit above its 4 GiB reserve. Both cross targets run in one process with one original-ZIP admission. They share one 768 MiB private, executable, nosuid/nodev tmpfs with at least 128 MiB free at entry. Only the package manager and the mount/unmount use the runner's sudo. Compilers, native children, QEMU and fixture scripts run unprivileged. The local source receiver uses a 512 MiB disk reserve and downloads the two small manifests/host logs, and the assembly log. It does not transfer an SDK to the development machine.

## Source and media preflight

With `QA` set to this source checkout, `COORDINATOR` set to a separate checkout of e408863e, `SUITES` set to the published 4fe6d1c0 checkout, and `OUT` set to a new private directory, the following commands can be repeated from the OSS checkout. `capture` can preserve a completed native producer before its sibling completes. `bind` refuses to write `bindings.json` until the entire existing producer workflow, including both ordinary smokes, succeeds.

```sh
python3 -IB "$QA/scripts/rc23-final-installed/test_receive.py" -v
python3 -ISB "$QA/scripts/rc23-final-installed/cross/check.py" preflight
python3 -IB "$QA/scripts/rc23-final-installed/receive.py" capture \
  --gh /home/dev-user/.local/bin/gh-auto --root "$COORDINATOR" --work "$OUT" \
  --training-source "$SUITES" --target aarch64-apple-darwin
python3 -IB "$QA/scripts/rc23-final-installed/receive.py" bind \
  --gh /home/dev-user/.local/bin/gh-auto --root "$COORDINATOR" --work "$OUT" \
  --training-source "$SUITES"
```

The reviewable `bindings.json` comes only from that final readback. The checked-in consumer requires identical official artifact and job identities on the native run. Each hosted output is named `qa-rc23-final-installed-<target>`.
