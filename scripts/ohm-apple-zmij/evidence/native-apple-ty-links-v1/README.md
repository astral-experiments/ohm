# Ruff language-server test links on Apple Silicon

On both unchanged `cargo test -p ty_server --test e2e --no-run` commands, the parent launched two Rust compilers and the Apple linker. Ohm Rust #276 launched none. After the real deleted-file diagnostics fix, both compilers rebuilt and relinked the e2e executable. Its test inventory grew from 194 to 195. The newly added regression and an existing diagnostics test passed. Both compilers rejected an additional invalid edit with E0425 and exit 101. Repair repeated the required link. Every returned executable matched its own independently empty build byte for byte. [Ruff #28988](https://github.com/astral-sh/ruff/pull/28988) · [Ohm Rust #276](https://github.com/astral-experiments/ohm-rust/pull/276) · [Paired native run](https://github.com/astral-experiments/ohm/actions/runs/41056076188)

| Focused command | Parent rustc / ld | #276 rustc / ld |
| --- | ---: | ---: |
| Build after the diagnostics edit | 3 / 1 | 2 / 1 |
| First unchanged test-build | 2 / 1 | 0 / 0 |
| Second unchanged test-build | 2 / 1 | 0 / 0 |
| Invalid edit | 2 / 0 | 1 / 0 |
| Repair | 3 / 1 | 2 / 1 |

The test-build used the normal Cargo defaults, the signed `-20` Cargo and the same stock Apple linker in all arms. The parent rustc was `2035696c5316079f5b2e4373aee834839aac97e9` and the candidate was `444c0273a2e2bc0b161e988d43c882349bc2d7a6`. Each arm started with separately empty worktree and shared build directories. The signed compiler served as a third independent check of the original behavior. [Signed native run](https://github.com/astral-experiments/ohm/actions/runs/41054731602)

The four independently clean e2e executables have the same machine instructions for the same Ruff revision across compilers. Their complete bytes differ in the native debugger’s object paths and corresponding code-signature page hashes. The optional whole-program replay below checks each original signed page, binds each rewritten field to one of the real Apple `ld` inputs, and compares every resulting byte. It checks 19,212 signed pages per executable on the edited revision.

## Workspace test build

On the same Ruff edit, `cargo test --workspace --no-run` returned 83 test executables. The parent called Apple's linker for 81 of them after the edit and on each of the next two unchanged builds. With #276, it called the linker for 60. The same 21 executables avoided a link on all three commands. All 83 executables matched the length and SHA-256 of the corresponding compiler’s independently empty build after the edit and on both repeats. The edited e2e binary contained and passed the new regression. [Paired workspace run](https://github.com/astral-experiments/ohm/actions/runs/41056076188)

| Workspace command | Parent rustc / ld | #276 rustc / ld | Parent / #276 test programs linked |
| --- | ---: | ---: | ---: |
| Build after the diagnostics edit | 108 / 99 | 74 / 66 | 81 / 60 |
| First unchanged test-build | 106 / 99 | 72 / 66 | 81 / 60 |
| Second unchanged test-build | 106 / 99 | 72 / 66 | 81 / 60 |

The workspace still recompiles `ron` once and the two `zlib-rs` units on each repeat. The workspace e2e executable still relinks once. Its actual linker command consumes both `ron` and `zlib-rs` archives. The focused e2e command above can already skip its link.

## Replay

Run from this directory with Python 3.11 or later.

```sh
sha256sum -c SHA256SUMS
python3 -IB verify.py
```

The compressed archives contain the original Cargo JSON, stdout and stderr of the selected libtest cases, and the kernel’s complete execution streams. The reader matches each native linker's actual output argument to the test artifact Cargo returned, proves the test name and exit status, and compares all the recorded SHA-256 values against independent clean builds. Originally relative configure-probe outputs are retained as relative paths. All measured test executables have absolute linker outputs. Only the two named language-server cases were executed outside the Cargo build.

To repeat the complete cross-compiler comparison with the original four clean executable files, download the focused artifact and pass it to the verifier. The original artifact SHA-256 is checked before decoding.

```sh
gh-auto api repos/astral-experiments/ohm/actions/artifacts/12978505922/zip > paired-focus.zip
python3 -IB verify.py --native-binaries paired-focus.zip
```

`project.py` reconstructs each portable stream archive from the matching full Actions ZIP. It verifies that ZIP's server-advertised SHA-256, reopens each command, and reruns the Cargo and native counts before packing its original streams. The Actions artifacts have a retention window. The compact streams and offline replay here are permanent.
