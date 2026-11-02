# Unchanged Ruff workspace links on signed Ohm -18 and -22

The same Linux worker needed **50 Wild links on -18 and 103 on -22** for the same 619 Cargo products on the first traced repeat. All 50 prior destinations still linked. Among the 53 added destinations, 32 directly report a native-input recheck. The other 21 report a dirty dependency that leads to the Unicode names build script. An isolated Cargo #330 comparison reproduced one added link with the same signed Rust and Wild and showed exactly which native error that policy avoids. These are physical work counts. The runs recorded no benchmark suitable for inferring elapsed time.

## Same-worker releases

Both signed archives were independently authenticated, including all 79 SDK files. Separate fresh Cargo homes, targets, build directories and registries used identical visible paths on one runner boot. Both verified all 498 locked archives, source tree `62d3f106c5e41f6022847f26ff8c7dc00139f7b1` and lockfile `c9e345325bec5ff08dbbe3916edd39ad0c3d1c7797a8c241ae32f62754e764bf`. The normal command was `cargo +ohm test --workspace --no-run --locked --offline -j8 --message-format=json`. Four visits per SDK included a cold build, an ordinary unchanged repeat, a repeat under process tracing and a repeat with Cargo fingerprint logging. Each visit subsequently passed the actual `ty_server:e2e` test `workspace_folders::single_file_workspace`. [Paired workflow and artifacts](https://github.com/astral-experiments/ohm/actions/runs/41395867548)

| Signed SDK | Dirty Cargo products on each repeat | Full rustc | Link-only rustc | Genuine Wild |
|---|---:|---:|---:|---:|
| -18 | 56 | 1 | 50 | 50 |
| -22 | 133 | 22 | 83 | 103 |

Kernel process ancestry ties each Wild output to one compiler and one actual typed Cargo product. On -22, 20 full compilers linked, alongside all 83 link-only compilers. The remaining two full compilers were Ron and Unicode names. The added link destinations include 50 executable products, two cdylibs and the Unicode names custom-build executable. The independent projection lists all 103. Every source build used plain Ohm defaults. [Signed-release readback](signed-18-22-results.json.gz)

The Cargo fingerprint trace identified one direct root on -18, Ron's foreign-span marker, and 55 dependency-dirtiness edges. On -22 it found Ron, 32 native-recheck roots and 101 dependency-dirtiness edges. Those 134 fingerprint rows include one build-script execution outside the 133 compiler-artifact rows. The verifier matched every reported dependency edge's two IDs against an independently captured 689-unit planner graph for the same Ruff commit, and anchored 614 IDs to actual unit labels on -18 and 536 IDs on -22. Fingerprints report their first reason. Of the extra links, 19 link-only and 13 full compilers directly cite the native marker. The other 21 first cite ruff_db (12), ruff_python_parser (4), unicode_names2 (3), or ty_module_resolver (2).

### Which ELF bytes changed

All 188 typed ELFs per SDK were hashed on each visit, including build scripts and shared objects. For each ELF, the acquisition also hashed every section payload, recorded the complete section headers and program headers needed for comparison, and hashed the complete file with just the GNU build-ID descriptor and the eight-byte `.rodata.sh_entsize` field masked. All runtime code and data, all other headers and all debugging payloads matched on consecutive visits. Every changed ELF differed only in the 32-byte GNU build ID and a 0/8 transition in that one section-header field. This matched the prior field-level finding on -20 and -21. [Earlier signed ELF readback](https://github.com/astral-experiments/ohm/blob/8e5bcb16e04cf2ffc37c105ce672f4c7d6313d5e/scripts/packaged-release-workspace/LINUX_RESULTS.md)

| Repeat against preceding visit | -18 changed whole ELFs | -22 changed whole ELFs |
|---|---|---|
| First, ordinary | ty_python_semantic | ruff_python_semantic, ty_ide |
| Second, process trace | ruff_python_semantic, ty_python_semantic | ty_ide |
| Third, Cargo fingerprint trace | ty_python_semantic | ty_ide |

A standalone Ron `.rmeta` also changed on -18. The complete `libunicode_names2`, `libruff_wasm` and `libty_wasm` rlib hashes changed on -22. Their individual archive members were not recorded, so the ELF section conclusion applies to the listed linked ELFs. An earlier independently acquired -22 run also counted 103 Wild invocations and returned a different subset of changed whole ELFs on a different boot. [Earlier -22 workflow](https://github.com/astral-experiments/ohm/actions/runs/41394504894)

## Why Cargo #330 adds a real Ruff link

The exact Cargo parent `2554a1dfaf22` and child `8269d772aa1e` used one signed -22 Rust and Wild on a separate matched worker. With the workspace's actual features, `cargo +ohm test -p ruff_text_size --test constructors --features get-size,schemars,serde --no-run --locked --offline -j8 --message-format=json` produced 53 Cargo products. Both compilers emitted identical compact_str dep-info, the sole checked-native marker in that selection. Parent ran zero rustcs or linkers on both unchanged commands. #330's recognition of the marker ran one genuine link-only rustc and one Wild on both commands. All six complete native Ruff executables were byte-identical and passed their real constructor test. [Source change](https://github.com/astral-experiments/ohm-cargo/pull/330) · [Source comparison](https://github.com/astral-experiments/ohm/actions/runs/41397147260)

A separate two-search-directory native fixture changed an external archive with Rust source held fixed. An earlier valid archive must change the program from 17 to 29, a repaired one to 41, and removal of the earlier archive must restore 17. Malformed bytes (same inode, size and mtime) and removal of both providers must make Cargo exit 101. On four of these five changes the parent kept returning the original executable. #330 matched all five independently empty verdicts and all three successful complete reference ELFs. A real Wild diagnosed both invalid states. This source comparison isolates one cause; it does not individually bisect all 53 extra workspace links or identify a compiler-codegen slowdown. [Thirty-command native readback](source-330-results.json.gz)

Download the entire Actions artifact as its original ZIP (preserving the outer digest), then reopen it with Python 3.11 or newer. The two earlier source harness attempts stopped before a compiler command. One lacked the explicit sibling-module import under isolated Python, and the other required the entire historical multi-architecture workflow to be green. The corrected check pins the successful x86 constructor job, its successful validation/upload steps, and the original aggregate result. [Import admission](https://github.com/astral-experiments/ohm/actions/runs/41396599088) · [Historical-job admission](https://github.com/astral-experiments/ohm/actions/runs/41396837910)

```sh
python3 -IB reopen.py 13120045929.zip 18ee5ba9c46b2b0ffe2c2ebe88cbeaaa8253b239c651314475e1c55afd5d36a6 > signed.json
python3 -IB reopen330.py 13119753687.zip 9e2e6231b0c115e473c25f9915125edf5abd74bdf7f79eb5977f874463552ffb > source.json
gzip -dc signed-18-22-results.json.gz | cmp - signed.json
gzip -dc source-330-results.json.gz | cmp - source.json
```

## The ordinary Ruff constructors program sees implicit system providers

Both Cargo sources linked the same Rust sources and unchanged signed -22 SDK on a new worker. An isolated, read-only overlay presented a single additional file in the actual GCC system directory, without changing any host-system or SDK files. The unchanged `-lutil` initially selected an 8-byte system archive. A previously absent `/usr/lib/gcc/x86_64-linux-gnu/13/libutil.so` containing an 85-byte GNU script selected a 2,168-byte native object. The actual Ruff test still passed and printed 29 from that object's initializer. The parent reused its old executable, which printed no initializer message. #330 ran Wild and matched the independent empty executable byte for byte. A malformed earlier script and a missing script-selected object both made the clean build and the separately forced Ruff target fail; the parent returned Cargo 0 in both cases. #330 correctly returned 101. Repair printed 41, and removing the override restored the original whole ELF. #330 performed full rustc after the preceding link failure on the missing/repair visits. All ordinary, unaffected and successful fresh references are included. [Native acquisition and 32 builds](https://github.com/astral-experiments/ohm/actions/runs/41398651348) · [Full syscall and ELF readback](constructors-inputs-results.json.gz)

The genuine unchanged Wild and its nine worker tasks observed 58 distinct failed library names with ENOENT, nine of them for `libutil` alone, plus three EINVAL readlinks on existing scripts. It successfully opened 74 distinct path spellings for reading. Of those, 70 unique regular inodes holding 25,286,010 bytes remained observable at link return. Twenty were root-owned. The 1,784-byte temporary `symbols.o` that Wild mapped had already disappeared. Five warm-page scans of the 70 files took 10.81–13.23 ms (median 10.96 ms), and lstat of the 61 native-name spellings took 92–106 µs. This explicitly excludes unavailable inputs and measures a post-link scanner. It gives no evidence for treating sequential hashes or file metadata as a coherent snapshot. Cargo's declared-archive shortcut covers plain executable targets with declarations; the constructors test had none. Wild's reference-link test cache also supplies no production Linux receipt. [Cargo #382](https://github.com/astral-experiments/ohm-cargo/pull/382) · [Wild #131](https://github.com/astral-experiments/ohm-wild/pull/131/files)

```sh
python3 -IB reopen_inputs.py 13120196874.zip c0bdfe211bae6b52ad1a5bd0b14c5428024ecfa5e6afca88204dbd39e939f42b > constructors-inputs.json
gzip -dc constructors-inputs-results.json.gz | cmp - constructors-inputs.json
```

## An authenticated pre-layout reuse on the constructors link misses a live native change

The source-built Wild prototype made six genuine receipt hits after resolving the actual files and GNU linker scripts. It hashed inputs from their open file descriptors, verified the complete rustc `symbols.o`, checked the current incumbent ELF's complete digest, and wrote those verified output bytes through Wild's original writer. It stored one 32-byte digest for each of three input states. This experiment required no saved copy of the executable. The separate test archive preserves each observed program as evidence. [Registered protocol](WILD_PREFLIGHT.md) · [Completed run](https://github.com/astral-experiments/ohm/actions/runs/41401051466)

| Unchanged physical link | Median retired user instructions | Range over six visits |
| --- | ---: | ---: |
| Signed -22 Wild | 81,011,092 | 80,439,393–83,628,093 |
| Same rebuilt Wild, full link | 81,161,185 | 80,707,936–82,793,347 |
| Same rebuilt Wild, receipt hit | 67,394,424 | 66,904,696–67,591,939 |

All 18 commands ran the genuine Rust link-only process and the expected native Ruff test. An x86 hardware event counted Wild's process and threads from physical exec, with independent main-thread, pthread and child calibration. Across the six counterbalanced orderings, the median within-pair ratio was 1.206× against the matched full linker and 1.204× against the signed linker. These are linker instructions alone. The initial observer stopped on the second genuine cold request to the same output and contributed zero primary observations. The registered replacement retained each physical process. [All native counts and outcomes](wild-native-evidence/verified.json.gz) · [First acquisition](https://github.com/astral-experiments/ohm/actions/runs/41400245165)

With stable inputs, the preflight matched stock's complete ELF for initial/29/41 and restored states. The higher script, malformed script, missing nested object and repair all changed the verdict correctly. Independently empty invalid inputs failed in the real build-script links before the root could run. The prior experiment also forced just the constructors root in each invalid state. Same-inode, same-size and restored-mtime incumbent corruption caused a full link and recovered the complete original ELF. An actual hardlinked output with two links and an actual symlink both took the original writer path.

The mutable input falsified the release gate. At the same real post-resolution/pre-layout boundary, the controlled writer changed offsets 180 and 181 in the selected 2,168-byte native object through an existing writable shared mapping. The original writing fd was already closed. Device, inode, size, mode, owner, group, link count, mtime and ctime all remained equal before and after on each run. A full matched link emitted the independently clean 41 executable, SHA-256 `65244fb0c00a895e9b56c5406e17a74bf23dbcbd0d81f500e84a403a16c566cc`. The receipt hit returned the former 29 executable, `cd6a352567277511bb3a8c268a32cce41f5c8cea4513dee60b7f14e2f21c7059`. Both native tests passed; their observed initializer values distinguished the wrong result. Subsequent signed stock links returned 41 in both histories. This rejects unrestricted Linux reuse for this target independently of the measured cost. [Private-source observation implementation](wild-diagnostic/observation_replay.rs) · [Kernel and native outcome verifier](reopen_preflight.py)

Both acquisitions have an indefinitely reopenable copy of every archived payload in this directory. Using a stored ZIP followed by a single Zstandard stream allows compression across similar raw documents. Every filename and member's bytes were compared to the original GitHub zip. Only the ZIP container layout changes. The successful archive retained 6,711 members, including all genuine ELFs, changing native objects, kernel records, CLI verdicts and raw counters, in 911,913 bytes. The interrupted acquisition retained all 1,164 members in 96,050 bytes. Its original ZIP and this replacement have separate whole-archive SHA-256 identities. [Successful capsule](wild-native-evidence/41401051466.zip.zst) · [Content commitments](wild-native-evidence/41401051466.json) · [Interrupted capsule](wild-native-evidence/41400245165.zip.zst)

```sh
zstd -dc wild-native-evidence/41401051466.zip.zst > /tmp/ohm-wild-constructors.zip
python3 -IB reopen_preflight.py /tmp/ohm-wild-constructors.zip 18b97ff23ee281263752476663a093aa31b9a847428bbc4c47696ab13850d1f9 > /tmp/ohm-wild-reopened.json
python3 -IB -c 'import gzip,json; a=json.load(open("/tmp/ohm-wild-reopened.json")); b=json.load(gzip.open("wild-native-evidence/verified.json.gz")); a.pop("archive_sha256"); b.pop("archive_sha256"); assert a==b'
```

### Can an ordinary linker exclude writers on every required input?

On the original observed link, Wild opened the root-owned system libc and libgcc_s. Their native fd `statx` reports supported immutable and verity attributes with neither set. A separate no-build worker on the same runner class queried libc, libgcc_s and libutil.a as UID 1001 with empty effective and bounding capability sets. All three were on the writable overlay. Each returned `EINVAL` for `F_GET_SEALS`, `ENOTTY` for `FS_IOC_MEASURE_VERITY`, and only the extents flag from `FS_IOC_GETFLAGS`. An ordinary reader could acquire a read lease on its private regular file, but a privately created equivalent owned by root gave `EACCES`. A preexisting writable mapping of the reader's own object gave `EAGAIN`, even with the original writable descriptor closed. The control used only read-only queries on the shared system inputs. One mandatory unsealed system file that the ordinary caller cannot lease is sufficient to rule out this protective condition for the observed link. The immutable evidence includes separate boot identity for the no-build control. [Unprivileged control](https://github.com/astral-experiments/ohm/actions/runs/41401765625) · [Original 1,871-byte JSON, gzip](wild-native-evidence/file-protection.json.gz) · [Source](protection.py)
