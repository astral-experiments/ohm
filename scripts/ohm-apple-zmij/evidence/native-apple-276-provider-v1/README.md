# Apple native input changes with a vector register comment

Native Apple-silicon run [41060913032](https://github.com/astral-experiments/ohm/actions/runs/41060913032). The only assembly in either Rust fixture is `asm!("/*{:v}*/", inout(vreg) vector)`. The program prints a value from an external Mach-O archive and a value from an ordinary Rust dependency.

Rust #275 `2035696c5316079f5b2e4373aee834839aac97e9` and #276 `444c0273a2e2bc0b161e988d43c882349bc2d7a6` used the same signed -20 Cargo `505008003127f597cf2bdbd967d2bac9158d706b55a18f8bf17790e9ea3bbac9` and Xcode linker `2b48a59af70235283aa94c43eb0dd2ef80182c106db43279db936cc87426b443`. The rebuilt drivers were `a1acdb5d6bd69c4ad88b6a0660d73a56bb53d1d6092c13c8ee057656392a01dc` and `fceefa2bb9730e4dcdc5ecde9ae68f929bbef63209c8a948100eaa203bfdf2c9`. The 2,465 other SDK member identities matched. The dynamic loader identified each driver during actual object emission.

## When only the native input changed

The package always supplied the same `-L` search order, first `early` then `late`. The declared case additionally emitted `cargo:rerun-if-changed` for both directories. In the unwatched case the build script watched only its own `build.rs`. “Direct” puts the register comment in the executable. “Library” puts it in a Rust library the executable calls. Both modes used private state and ordinary incremental dev builds. “Off” selects `cargo +ohm -Zohm-defaults=no`.

Each cell shows the two runtime values or Cargo exit 101, followed by (full rustc invocations / observed Xcode linker invocations naming the external provider). All independently empty builds printed `29 7` for the higher archive and rejected malformed and missing providers with Cargo 101.

| Placement | Watch | Cargo | Higher #275 | Higher #276 | Malformed #275 | Malformed #276 | Missing #275 | Missing #276 |
|---|---|---|---|---|---|---|---|---|
| direct | declared | default | 29 7 (1/1) | 29 7 (1/1) | 101 (1/1) | 101 (1/1) | 101 (1/1) | 101 (1/1) |
| direct | declared | off | 29 7 (1/1) | 29 7 (1/1) | 101 (1/1) | 101 (1/1) | 101 (1/1) | 101 (1/1) |
| library | declared | default | 29 7 (2/1) | 29 7 (1/1) | 101 (2/1) | 101 (1/1) | 101 (2/1) | 101 (1/1) |
| library | declared | off | 29 7 (1/1) | 29 7 (1/1) | 101 (1/1) | 101 (1/1) | 101 (1/1) | 101 (1/1) |
| direct | unwatched | default | 29 7 (1/1) | 17 7 (0/0) | 101 (1/1) | 29 11 (0/0) | 101 (1/1) | 29 13 (0/0) |
| direct | unwatched | off | 17 7 (0/0) | 17 7 (0/0) | 29 11 (0/0) | 29 11 (0/0) | 29 13 (0/0) | 29 13 (0/0) |
| library | unwatched | default | 29 7 (2/1) | 17 7 (0/0) | 101 (2/1) | 29 11 (0/0) | 101 (2/1) | 29 13 (0/0) |
| library | unwatched | off | 17 7 (0/0) | 17 7 (0/0) | 29 11 (0/0) | 29 11 (0/0) | 29 13 (0/0) | 29 13 (0/0) |

A successful `29 11` after malformed input is the previously linked program, following an earlier successful Rust edit. The frozen Apple matrix covered the two source-built Ohm compilers and signed Ohm Cargo.

All 24 directory-watched higher/malformed/missing transitions ran the actual build script and final Apple linker. The equivalent 24 unwatched transitions never executed the local build script. Endpoint Security captured those subprocesses. Cargo JSON recorded both emitted search paths in every command. The collector found no separate build-script stdout files at its probed filenames; the watch declaration is authenticated from the complete fixture source, and the resulting executions are authenticated from the kernel records.

## Genuine Rust edits

64/64 changed-Rust observations matched their independently empty outcome. Changing the Rust dependency made the higher archive print `29 11`, the malformed/missing archives with source values 13/15 reject, and the repaired lower archive print `17 19`. The 32 edited successes had byte-identical whole Mach-Os to empty; the 32 edited failures rejected in both. Xcode reported `unknown file type` for the malformed archive and `library 'qa_owned_external' not found` after removal.

The 352 Cargo commands issued 874 full rustc invocations, 0 link-only rustc invocations and 502 Xcode linker invocations, of which 310 named the program’s provider. Other linker invocations built the local build script. The evidence includes 236 executed programs and 116 Cargo 101 failures. The reader reopened all 50 distinct full Mach-Os.

Of 176 warm/empty pairs, 106 produced byte-identical executables. In 6 pairs the binaries printed different values. There were 12 warm successes whose empty counterparts rejected and 52 pairs where both rejected. Equal runtime with different raw binaries occurred in 0 pairs.

In the early direct default control, #275 emitted the hard depfile marker. #276 emitted the advisory marker in its internal depfile, and its public depfile contained neither. Signed Cargo removes the recognized advisory operand from the freshness list. The verifier reads these flags from the actual depfiles. [Signed Cargo dep-info reader](https://github.com/astral-experiments/ohm-cargo/blob/2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c/src/compiler/fingerprint/dep_info.rs#L691-L734)

## Reopen and reproduce

Run `python3 -IB verify.py` in this directory to check the compact observations. With the original CI artifact, `python3 -IB verify.py --raw /path/to/apple-276-external-provider-receipts.zip` independently reads Cargo JSON, per-command kernel exec records, native search order and outputs, archive members, depfiles, program exits/stdout and complete binaries. It authenticates each loaded driver and the signed Cargo. The compact observations contain diagnostic path placeholders and commitments to full original streams. No clocks were collected.

Final artifact 12979676639 was 12,046,021 bytes, SHA-256 `9417834052f28ffd0ce5f13ed59e899093a294b7ac692c7a53e8b4965a3e3c77`. All 317 files from the separately published 44-command checkpoint were reopened byte-for-byte from the final ZIP. `custody.json` binds both archives and the SHA-256 manifests of their individual members.

The pinned private QA workflow and its `provider_edges.py` reproduce collection on an Apple runner with Xcode and Endpoint Security. It builds both original Rust commits, authenticates the signed Cargo and gives each native visit an independently empty build at the same paths. The Rust fixture itself has no registry dependencies. [QA source and workflow](https://github.com/astral-experiments/ohm/tree/1c8e729a327b8c1debc40f7c7621d91af425c9a7)
