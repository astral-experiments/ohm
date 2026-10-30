# An implicit Linux library changes Ruff's generated Unicode table

Ruff’s unchanged host build for `ruff_unicode_names2` returned the old Unicode value after a shared library appeared in the directory Cargo uses to select Wild. Stock Wild and the Ruff build script both opened this library on a clean build. All source files, the compiler, the linker and user flags stayed the same. The Cargo command was `cargo +ohm build -p ruff_unicode_names2 --locked --offline -j4 --message-format=json`. The tracked Ruff tree contained the ordinary `chacha20` build dependency and its compiler-generated v1 recheck marker. [Ruff commit](https://github.com/astral-sh/ruff/tree/93526150df078af7dd8fc4226cdcc469539d2001/crates/ruff_unicode_names2)

| Unchanged input transition | Signed Cargo #294 | #294 + versioned reader fd55 | #293 and #301 | Each independently empty build |
| --- | --- | --- | --- | --- |
| No private library | 0 | 0 | 0 | 0 |
| Introduce a valid earlier provider | 0 | 0 | 83 | 83 |
| Replace bytes in the same inode, preserving size and mtime | 0 | 0 | 47 | 47 |
| Replace bytes with a malformed library, preserving size and mtime | 0 | 0 | Cargo 101 | Cargo 101 |
| Remove the provider | 0 | 0 | 0 | 0 |

The numbers in successful cells are values returned by a separately compiled executable calling `unicode_names2::character("NULL")`. Its `"NUL"` control always remained zero. The signed and fd55 roles ran zero Rust compilers and native linkers on all five warm returns. Both strict readers ran the real build-script compiler and stock Wild once on each return, including the initially unchanged absence. On the two changed valid states they also compiled the library. The first no-change return labeled two typed units dirty while one real rustc ran. The archive retains that distinction. The matching full reader ELF and three generated Rust files agreed with the matching clean output in every correct cell. Raw rlib hashes can differ across independent installations and are included. These results cover old v1 dep-info. #301 retained its #293 parent’s behavior here. fd55 is the separately tested merge of #294 and #301, which inherits the signed #294 treatment of v1. [#293](https://github.com/astral-experiments/ohm-cargo/pull/293) [#294](https://github.com/astral-experiments/ohm-cargo/pull/294) [#301](https://github.com/astral-experiments/ohm-cargo/pull/301)

## The private intervention

The experiment made a separate SDK directory. It copied the signed rustc executable and driver so rustc reported that private sysroot. Unmodified tools and libraries were resolved through read-only source references. Cargo was selected by source and executable digest for each arm. The sole new native candidate was `<private-sysroot>/lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/libutil.so`. The signed installation contained no such file and received no writes.

Cargo itself passes `-B<sysroot>/…/wild-ld -fuse-ld=bfd` to GNU cc. GCC’s collect2 passed a corresponding `-L…/wild-ld` to the signed Wild binary. The Rust standard library supplies `-lutil`. The fixture added no Cargo configuration, user rustflags, source change, link-search declaration, `LIBRARY_PATH` or `LD_PRELOAD` to introduce its input. Each real provider has the private absolute filename as its ELF SONAME. Its `__libc_start_main` interposer invokes the original executable. After the genuine Ruff generator succeeds, the provider changes one generated alias in its own private `OUT_DIR`. This makes the otherwise implicit native dependency observable in the compiled Rust library. `provider.c` records the complete intervention. The test deliberately installs a new file beside a private copy of the linker. It makes no claim that such a file exists in a signed distribution. [Cargo’s GNU linker selection](https://github.com/astral-experiments/ohm-cargo/blob/c18e91b514b2c4e4966c9ab03232c804af3e1b57/src/compiler/ohm_linker.rs)

In a separate stock-Wild trace of the same unmodified command, the absence produced a real `statx(.../wild-ld/libutil.so) = ENOENT`. Wild subsequently opened the ordinary system `libutil.a`. Insertion turned the earlier probe into a successful `statx` and an `openat` for the new DSO. A separate kernel open by the Ruff generator proves the loader selected it at run time. The six Wild process/thread IDs made 69 distinct successful open spellings and 70 distinct failed spellings with the provider absent. The corresponding counts after insertion were 69 and 65. The baseline included real `libgcc_s.so`, `libc.so` and `libm.so` linker scripts. These counts describe the observed runs. A positive-only dependency list omits the original failed search. Rustc’s transient symbols and codegen objects also disappeared after the process exited.

## Verify the original observations

```sh
sha256sum -c SHA256SUMS
python3 -IB verify.py
python3 -IB verify.py --full
```

The verifier parses actual successful exec records, observable generator opens, raw diagnostic messages and reader stdout. It checks all 40 Cargo visits, 16 independent empty references, the device/inode/mtime/size controls and three complete reader digests. It follows the clone edges for the two independent Wild captures. Five deliberately corrupted cases must be rejected. `commands.json.gz` and `search.json.gz` retain the evidence after replacing private checkout, SDK and registry path prefixes with role names. Hashes identify the original byte streams. `portable-smoke.json` records a separate 20-command replay of the signed and #293 roles. Its real executable hashes are compared to each role’s own independent clean runs at the new absolute path. The relocated #293 no-provider settled visit started two rustcs (build script and library), versus one on the original host layout. Both ran stock Wild once and returned the correct reader. The separate acquisition used a private tmpfs on a read-only host and adds no timing samples.

## Rerun on x86-64 GNU Linux

Use the released Linux SDK, a rustup proxy directory, a checkout of the exact Ruff commit and an offline Cargo registry containing that workspace’s locked crate inputs. Python 3.11+, GNU cc on glibc, readelf and strace with permission to trace children are required. A new, executable work directory must have the 2.75 GiB standing reserve plus 300 MiB of free space. The three original alternative Cargo assets have independent SHA-256 checks in `identities.json`. GitHub Actions may expire these ancillary QA artifacts. The signed-only replay requires only the durable release. [Signed SDK release](https://github.com/astral-experiments/ohm/releases/tag/ohm-1.99.0-20) [#293 build](https://github.com/astral-experiments/ohm/actions/runs/41076211398) [#301 build](https://github.com/astral-experiments/ohm/actions/runs/41081958994) [fd55 build](https://github.com/astral-experiments/ohm/actions/runs/41108155677)

```sh
python3 -IB replay.py "$PWD/replay-signed" \
  --roles signed --signed-sdk "$SIGNED_SDK" --ruff "$RUFF" \
  --registry-home "$CARGO_HOME" --rustup-bin "$HOME/.cargo/bin"

python3 -IB fetch-readers.py "$PWD/original-readers"
python3 -IB replay.py "$PWD/replay-all" \
  --signed-sdk "$SIGNED_SDK" --ruff "$RUFF" \
  --registry-home "$CARGO_HOME" --rustup-bin "$HOME/.cargo/bin" \
  --classic-cargo "$PWD/original-readers/classic" \
  --aware-cargo "$PWD/original-readers/aware" \
  --fd55-cargo "$PWD/original-readers/fd55"
```

The acquisition checks exact compiler, linker, Cargo and Ruff source identities before running. Each per-role warm target and each empty reference starts in its own, independently emptied private target/build directory at the same logical path. The harness compiles and executes the independent reader after each successful Cargo command. Its compiler and linker are outside the Cargo process census. Both wrong and correct outcomes are required for this reproduction to pass. The local directory used for the original three-DSO state reader hashes can differ from the reviewer’s full path. Within a replay, the verifier compares the complete emitted reader and all generated bytes with that replay’s own clean states.
