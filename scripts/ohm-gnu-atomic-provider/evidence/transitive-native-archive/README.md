# GNU AArch64 provider in a transitive Rust archive

A real Rust executable loaded a C static through a plain middle crate and then passed its address to a leaf containing `ldar`. The intermediate crate owned the native library. The readback covers 630 Cargo commands in 70 independent histories. Each program was a GNU AArch64 ELF executed under QEMU.

## What happened

On Cargo #301, the parent and proposed leaf classifier both kept the old bundled word 17 when an unwatched native library changed in place or a higher-priority library appeared. A forced final link still saw the old object inside the middle crate’s existing rlib. Forcing that crate to rebundle, or starting with an empty target at the same path, returned 29. Malformed data at the selected or higher path, and complete removal, yielded a warm Cargo exit 0 and program output 17. The forced rebundle and empty builds exited 101. Repair after forcibly bundling 29 also required a rebundle to return to 17.

Both compilers agreed on program output or exit failure and on the embedded provider bytes in all 108 matched commands. On an ordinary unwatched transition, the parent compiled the leaf and app, and the candidate compiled the app. Both invoked the GNU linker. With `-bundle`, both saw all five provider mutations correctly. Declaring both search directories also caught the new higher-priority provider in both compilation modes. The original cases and source-bound SDKs are retained with their action run. [Original 216-command run](https://github.com/astral-experiments/ohm/actions/runs/41139771526) · [Registered source](https://github.com/astral-experiments/ohm/tree/e46fcee1579af2823f8413944635a8314086bf75/scripts/ohm-gnu-atomic-provider)

Unmodified upstream Rust/Cargo 1.99, signed Ohm -20 Cargo with defaults disabled and enabled, and strict Cargo #293 with both Rust compilers all shared those five bundled failures. In the upstream and signed-opt-out runs there were zero compiler and linker processes on these warm calls. A checked consumer link cannot change bytes already archived by another crate. The evidence identifies an existing Cargo declaration boundary for this topology. [414-command receiver comparison](https://github.com/astral-experiments/ohm/actions/runs/41140657396) · [Registered source](https://github.com/astral-experiments/ohm/tree/967e019be307dc17376fd44bcd09322bd4b8c590/scripts/ohm-gnu-atomic-provider)

| Build-script declaration | New earlier provider | Rewrite selected file with new mtime | Same inode, length and mtime |
|---|---|---|---|
| Both search directories | Correct 29 | Correct 29 | Stale 17 |
| Previously selected file alone | Stale 17 | Correct 29 | Stale 17 |
| Both candidate filenames | Correct 29 | Not tested | Not tested |

The table uses the full upstream and signed-defaults-off controls. With both candidate filenames declared, Cargo also rebuilt the middle crate and app while the earlier path was still absent. Its directory declaration settled to zero compilation in both conventional controls. The same-mtime test changed the input digest while preserving device, inode, size and nanosecond mtime. Cargo documents mtime-based build-script monitoring and recursive directory scans. [Build-script reference at the signed revision](https://github.com/astral-experiments/ohm-cargo/blob/2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c/doc/book/src/reference/build-scripts.md#rerun-if-changed)

## Scope and replay

The Rust parent reviewed at `0f6951eb` was reconstructed as `6ae50e2d`; the candidate reviewed at `cfb92189` was reconstructed as `4ed3e4d1`. Their native SDKs differ only in the compiler driver. Each restored SDK had 119 installed files. The original two arms used Cargo #301 (`c18e91b5`). Receiver controls used lifetime-distinct binaries from upstream Rust 1.99 (`b940084d`, Cargo `5f94df478`), signed -20 Cargo (`2d44bd4a`) and #293 (`735e1528`). Signed on/off used the measured parent Rust. `strict-P` and `strict-C` varied only that compiler driver under #293. The source, native tool and member manifest digests are in `commands.json.gz`.

Nine Cargo commands per history cover the empty baseline, settled baseline, first ordinary mutation, repeat, forced root, forced rebundle, independent empty mutation, ordinary repair and independent empty repair. Each included case has an independently compiled C reference and a physically opened baseline archive. The stock and signed-opt-out cases bound to conventional defaults include directory insertion, selected-file-only and preserved-mtime probes. Declared-directory malformed/removal was not a matched experimental endpoint in this series. No timings were scored.

Run the compact readback offline with Python 3.11 or newer.

```sh
python3 -IB verify.py
```

For full native verification, download the seven original artifacts from the two linked runs into `RECEIPTS/<run-id>/<artifact-name>.zip` and run the following. The packet retains each artifact's ID, original SHA/size and digest of all archived entries. The full verifier opens every retained ELF and rlib, checks the embedded C object, redecodes each original per-PID exec/open stream, and checks the actual QEMU output and Cargo diagnostics. The underlying final linker was GNU ld through the AArch64 GCC cross driver.

```sh
python3 -IB verify.py --raw RECEIPTS
```
