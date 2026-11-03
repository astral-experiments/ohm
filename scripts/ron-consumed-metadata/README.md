# Inputs read by the signed Ron compiler on Ruff #29697

An unchanged Ron shortcut needs to validate at least one more crate than the six explicit `--extern` arguments. The real compiler found the 4,244,611-byte `serde_core` metadata file through a dependency search directory. Corrupting its first byte produced E0463, including in a fresh installation. Restoring that byte restored the complete Ron archive and a working consumer. The ordinary Ron dep-info omitted this file.

The optional binary dep-info did list `serde_core`. In a successful compile it recorded the BLAKE3 of a different file installed at that name **after** rustc mapped the good file. The same malformed file, present from the start, failed compilation. This is a Linux file-generation control on a real compiler invocation. The reduced official Rust control reproduced the optional behavior. These runs do not measure 50 native links or establish a default Cargo release regression.

## Reproduce

From this directory on Linux x86-64, verify the captured artifacts with Python 3.11+, `zstd` and `b3sum`. This check runs offline.

```sh
python3 -IB verify.py
```

To execute the original Ron compiler command and the native controls, use the unpacked signed SDK, rustup proxies on PATH, GNU `ar`, a native C linker, `strace`, and a new private directory. The supplied `--sdk` must contain `bin/rustc` directly. The Linux SDK archive SHA-256 is `fc85a2ca6d47711058cd89c790c8e57f1799472e38f0ee0a08b0a51d06c1ee7b`. The runner checks each of the 79 registered files and the actual rustc version. The command uses inotify, signal stops, and read-only access to the child process's maps and memory. Child tracing must be permitted for `--trace` and the jobserver control. [Signed SDK](https://github.com/astral-experiments/ohm/releases/download/ohm-1.99.0-23/ohm-1.99.0-23-x86_64-unknown-linux-gnu.tar.gz)

```sh
python3 -IB replay.py --sdk /absolute/path/to/signed-sdk \
  --work /absolute/new/ron-study --trace
python3 -IB jobserver.py --work /absolute/new/ron-study
```

To also reproduce the independent official control in the same command, add `--stock-rustup-home /absolute/path/to/private-stock-rustup` to `replay.py`. That directory must register the genuine Rust 1.99.0 toolchain as `toolchains/ohm`. Its rustc commit is checked. Only that optional upstream fixture sets `RUSTC_BOOTSTRAP=1`, to select the two unstable dep-info flags. Both replay programs retain outputs in the supplied private directory and refuse an existing destination for their evidence. `--b3sum /path/to/b3sum` selects a particular BLAKE3 tool.

## What the real process touched

The input capsule comes from the actual signed Ron compiler in the full Ruff #29697 role. Original Actions run 41623657148, artifact 13225550728, ZIP SHA-256 `74933fe90daeb5b2b8d0b4ec48bd9d84356a7991028cf185c0734e744b930acc`. The small materialization contains 36 original content-addressed bytestrings, including eleven locked crate archives used to restore 519 source files. No crate archive was read by this rustc. `inputs/invocation.json` binds the source paths, compiler arguments, and selected environment. `jobserver.py` independently restores the captured Cargo ABI on its own pipe. Rustc is signed Ohm `d57fd1515986dccecdcece8da85e651bfb4b81f9`; the release Cargo pin is `7024b0d2dc5f64bba72c0d6d28f537a5cd9707ed`. The diagnostic here directly invokes the compiler. [Original Actions run](https://github.com/astral-experiments/ohm/actions/runs/41623657148)

| Observed existing inputs | Distinct regular files | Full bytes of those files |
|---|---:|---:|
| Ron source and included README | 19 | 272,837 |
| Explicit `--extern` metadata | 5 | 1,289,965 |
| Explicit and actually executed serde_derive DSO | 1 | 4,902,736 |
| Transitive serde_core metadata | 1 | 4,244,611 |
| Standard library files mapped from the SDK | 20 | 88,374,044 |
| Rust compiler driver and LLVM runtime | 2 | 370,815,968 |
| Eight host DSOs and `ld.so.cache` | 9 | 6,056,915 |

File sizes give the cost of hashing each complete ordinary file once. They do not report pages faulted in. The file/descriptor census records seven dependency search directories, the SDK library directory, and three private output directories. The trace includes 100 failed file operations over 77 distinct absent names. Seventeen are alternative Ron module paths. The projection keeps each spelling, errno, scope, and count. It also separates private temporary/output files, device/procfs reads, and random-number requests. A system call trace is not evidence that every observed path actually influenced code generation. It also cannot enumerate arbitrary in-process environment reads or vDSO calls.

The ordinary Cargo binary dep-info retained 19 Ron inputs and the foreign-span marker. It had zero file checksums. Its authenticated OBS1 trailer pointed to the marker at file index 3. The actual proc-macro bridge made 68 span joins, with three observed foreign calls/returns and zero Debug calls. The recorded foreign file was `bitflags-2.13.2/src/public.rs`. The raw event projection and the original six loader controls retain this boundary. A changed, valid DSO image differing at two actual bytes caused two E0782 errors, including an expansion at the foreign source. The six explicit arguments already include this DSO.

With `-Zbinary-dep-depinfo -Zchecksum-hash-algorithm=blake3`, the .d file contained 45 checksums and the marker. These cover Ron's 19 inputs, the six explicit artifacts, the transitive `serde_core`, and nineteen standard metadata files. The twentieth observed standard file was `libstd_detect-90b5259d92b4976a.rlib`, which rustc mapped and did not record in that emitted list.

## Which generation was recorded

The receiver stopped its own genuine rustc after the first open of the selected private metadata, while its original inode was mapped `r--p` at offset zero and no dep-info had been emitted. It captured the dev/inode in `/proc/PID/maps`, the raw first 16 bytes through `/proc/PID/mem`, and the bytes at the pathname. All paths outside the two private installations remained untouched.

| Action while stopped | Mapped magic just before resume | Path at resume | Exit | Checksum emitted |
|---|---|---|---:|---|
| Keep good file | `rust` | good | 0 | good |
| Rename malformed file over path | `rust` | malformed, different inode | 0 | malformed |
| Change first byte in place, then restore before resume | `rust` | good | 0 | good |
| Change first byte in place, preserve size and mtime | `Rust` | malformed, same inode | 0 | malformed |
| Start with malformed file in either independent Ron installation | — | malformed | 1 | E0463 |

The valid BLAKE3 was `49392d1a30ee41a713189a97243423f341982a1b8bb9c57dd120261f62fbefc6`. The malformed BLAKE3 was `3e98aac3721f4b6ec1631e7a596c0b854268a287db381027f7d50dcfb0dedd78`. A later rename after the checksum read retained the good digest. This distinguishes the consumption and emission boundaries. In the in-place case, the compiler had already passed the metadata header check. The independent clean failure demonstrates the actual consequence of corrupting that header from the start.

The ordinary reference and traced build agreed on the complete .rlib and .d. Their standalone .rmeta files differed at 56 bytes associated with two opaque-lifetime indices. All 3,584 per-definition fingerprints, 3,240 local rows, 1,232 expansion rows and 26 dependencies agreed after resolving those indices. Eleven original positive artifacts each linked and ran a consumer. Every execution round-tripped `[8,13,21]` and rejected malformed input at line 1, column 5. A real invalid consumer produced E0308. Repair restored the complete executable. Complete executable bytes matched within a fixed source-path history.

A new public-recipe run repeated the whole sequence from the input capsule, including an independently empty provider installation. At the same paths the ordinary and optional commands also produced byte-identical consumer ELFs. All twelve archive member names and eleven complete member bodies agreed across the two different command lines. Only the 16-byte region at offsets 213–228 of the 736-byte `lib.rmeta` stub could differ. Each individual command line required exact complete .rlib equality across its controls. This preserves a failed early portable check that assumed the whole archive was independent of the two compiler flags.

## What would make reuse sound here

Both compiler sources enumerate the selected crate through `used_crate_source` and subsequently open its pathname while emitting the optional checksum. The released loader maps the complete standalone .rmeta into an `OwnedSlice`; official Rust 1.99.0 does the same. An owned *mapping* keeps the old inode across rename. It does not freeze the file bytes against an in-place writer. The common mmap API explicitly requires the caller to prevent concurrent modification. An independent official Rust native fixture reproduced the good mapping/malformed emitted digest and failed E0786 from a clean malformed input. This confirms the optional mechanism for that smaller fixture. [Signed dep-info](https://github.com/astral-experiments/ohm-rust/blob/d57fd1515986dccecdcece8da85e651bfb4b81f9/compiler/rustc_interface/src/passes.rs#L649-L702) · [Upstream dep-info](https://github.com/rust-lang/rust/blob/b940084d7eb6a299eb4bfeb8e34901bc051e7ac4/compiler/rustc_interface/src/passes.rs#L625-L698) · [Signed metadata loader](https://github.com/astral-experiments/ohm-rust/blob/d57fd1515986dccecdcece8da85e651bfb4b81f9/compiler/rustc_metadata/src/locator.rs#L930-L946) · [Upstream metadata loader](https://github.com/rust-lang/rust/blob/b940084d7eb6a299eb4bfeb8e34901bc051e7ac4/compiler/rustc_metadata/src/locator.rs#L926-L942) · [mmap contract](https://github.com/rust-lang/rust/blob/b940084d7eb6a299eb4bfeb8e34901bc051e7ac4/compiler/rustc_data_structures/src/memmap.rs#L14-L31)

A feasible narrow design for standalone metadata would feed the decoder and the checksum from the exact same owned, immutable bytes, or from a generation the kernel guarantees cannot be written. For this input a private owned copy requires touching 4,244,611 bytes that ordinary mmap can fault in lazily. The current loader owns the view but does not establish that guarantee. Hashing its view at entry or exit still permits a write between hashing and parsing. The digest could live in existing dependency evidence. A second persistent object cache is unnecessary for this step.

Reusing the complete Ron result would additionally require validating the actual selected proc-macro image and observed foreign-source context, compiler/SDK closure and options, and resolving any relevant higher-priority names or missing source module paths again. Authenticated immutable toolchain inputs can share an identity. Mutable system paths, arbitrary native macro effects, and a concurrent save after observation require a stable generation or an ordinary compiler fallback. These measurements supply a rejection of the reduced six-argument shortcut and a test for one necessary metadata guarantee, without a product change.
