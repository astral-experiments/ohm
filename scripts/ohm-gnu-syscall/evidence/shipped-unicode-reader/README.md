# Unchanged native Ruff Unicode build on shipped and proposed Cargo

`cargo +ohm build -p ruff_unicode_names2 --locked --offline -j4` on the same signed Ohm 1.99.0-20 Linux compiler, SDK and Wild, using Ruff `93526150df078af7dd8fc4226cdcc469539d2001`. Each Cargo and target mode starts with empty target and build directories. Run three consecutive builds in each. The ordinary host command and the explicit x86_64 native target give the same result.

| Cargo | Cold | First unchanged | Second unchanged |
| --- | ---: | ---: | ---: |
| Shipped #294, `2d44bd4aa6` | 17 | 0 | 0 |
| #293, `735e1528ed` | 17 | 2 | 2 |
| Versioned reader on #293, `c18e91b514` | 17 | 2 | 2 |

Counts are non-fresh Cargo product messages. A separate settled kernel trace confirms zero actual rustc/linker processes on the signed release. On the proposed reader it records two actual rustcs (the Unicode build script and the Unicode library), one real ld.bfd invocation and execution of the build script. The generator produced the exact same three Rust source files across all three builds in each case. The only archive member with changed contents between warm repeats was `lib.rmeta-link` after accounting for per-session .rcgu.o file names.

The new versioned reader matches its immediate #293 parent on this workload. Both are on a different Cargo branch from the signed release. A springboard for a release needs to retain the legitimate warm host skips while preserving the native dependency checks for the new protocol. This example does not establish a speedup against the signed Cargo. All recorded commands exited successfully.

Run `python3 -IB verify.py` in this directory. The small archive contains the original Cargo JSON/stderr for all 18 commands, the two original settled execve traces and Cargo JSON streams, member/generator hashes and Cargo source/binary identities. Kernel tracing observes a warmed command following an identically traced warmup. No wall-clock timing is used.
