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
