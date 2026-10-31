# Complete release smoke on the original -22 distributions

The manually dispatched QA workflow reuses the original release candidate from run 41237680370. Its two Smoke release jobs stopped at the nested linker smoke. This replay runs the entire checked-in outer smoke and its corrected relink script, then exercises an actual linked Git worktree. It requires Ubuntu 24.04 x86-64 and the native namespace macOS 15 arm64 runner used by the original release.

| Input | Frozen identity |
| --- | --- |
| Original packaging source | 007da57ba792129adb5754546e1158e7e6d732b7 |
| Source of both smoke scripts | e8468d0d0221379e7152a748a8735d78a88eda2f |
| Global ZIP with installer and SHA256SUMS | 13059239725 |
| GNU / Darwin original release ZIPs | 13057710231 / 13058479585 |
| Original installed Rust / Cargo | 556a8364f1485a03be31b1a50c250d63198a943d / 8269d772aa1ef02e5efaa331dfb40eb55d71f719 |
| Private corrected Cargo and source tree | 4591cf45cc10abb19d2456c40b99606e08167f29 / a2c9a62722e1ef849cb68874e79617c92d165a8b |
| GNU / Darwin source-built Cargo donor ZIPs | 13046543047 (41212542603) / 13047576657 (41212939515) |

The source job and nested archive hashes, file sizes, Cargo hash per host and upstream 1.99.0 analyzer component hashes are in [registration.json](registration.json). Each ZIP must match its successful producer step and original attempt, including the failed overall release or QA run it belongs to. The installer and archive are served through a local file URL. Both installations use the same authenticated registry crate, Clippy, rustfmt, compiler, rustdoc, Rust source, host and wasm standard libraries, and platform linkers. Stock rust-analyzer comes from the original upstream 1.99.0 distribution. The GNU installer carries its existing Wild binary. The Darwin smoke checks the system paths of linked dependencies.

The first arm sources the complete original outer shell unchanged and uses the corrected helper under its original filename. The second arm starts from a fresh original installation and inserts one call immediately after the installer returns. That call atomically replaces its Cargo executable with the independently authenticated four-fix build. Before and after hashes are retained. This private combination uses the packaged Rust SHA even though draft #225's Rust pin ceafeeda61cc18293545cc4e4039099cdabc0be3 points at the same compiler/library through a different Cargo gitlink.

The outer smoke supplies the installer, four nested compiler/link checks, Clippy/rustfmt tools, native build with defaults enabled/disabled, wasm, docs, native registry sharing, and stock rust-analyzer diagnostics. GNU additionally executes real native run and test with lld and Wild and checks linker ELF notes. A final native worktree control reuses itoa, produces child values 42 then 73, preserves 42 in its parent and requires E0277 from a real wrong-typed child edit. All writes are confined to new private installations and temporary projects. No publication, release environment or build of a distribution is involved.

A failure retains the original compressed stdout, stderr and shell command trace. Only a genuine last failing invocation of the separate relink helper allows a fresh residual run. Its staged source replaces just that invocation with a note and repeats the remaining work. The whole arm still fails, and independent full acceptance rejects any residual. An unrelated later failure has no bypass. Failure in the original arm still allows independently checking the private fixed arm.

After review, push the exact QA head and dispatch its manually gated CI workflow once:

    git push origin HEAD:refs/heads/charlie/qa-rc22-complete-input-smoke-20261031
    gh-auto workflow run ci.yml --ref charlie/qa-rc22-complete-input-smoke-20261031 -f source=41237680370 -f reviewed_head="$(git rev-parse HEAD)"

Each QA artifact contains raw tool transcripts, archive and installed measurements, the native/wasm/doc output hashes, the actual Git worktree command streams and its diagnostics. From this checkout, independently read a detached receipt directory:

    python3 -IB scripts/rc22-complete-smoke/reopen.py extracted-receipts

Use --local only for the separately labelled GNU devbox rehearsal with the authenticated upstream analyzer component. Hosted qualification additionally requires the original Actions run/job/artifact records and the separately installed stock compiler's reported version and host.
