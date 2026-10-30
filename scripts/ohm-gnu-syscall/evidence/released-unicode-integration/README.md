# Native Ruff Unicode builds on the released Cargo lineage

A source integration on top of the released Cargo keeps every unchanged native `ruff_unicode_names2` build fresh. The earlier receiver on #293 rebuilt both the Unicode build script and its library on each unchanged native build. The merge checks the compiler's depfile rule and preserves the released handling of its older advisory marker. Rust's versioned marker still requests native-link revalidation. This is an experimental merge. Its broader native-provider and older-compiler compatibility qualification is separate. [Original release comparison](../shipped-unicode-reader/) · [Source and reproduction](../../release-reader/)

The signed Linux `-20` rustc and Wild built identical Ruff source (`93526150df078af7dd8fc4226cdcc469539d2001`). Each reader started with empty build directories. Both the ordinary host command and an explicit host target gave the counts below. Each entry is **full build rustcs / native linkers**, counting processes on the warm commands.

| Phase | Signed Cargo #294 | Integrated Cargo |
| --- | ---: | ---: |
| First unchanged | 0 / 0 | 0 / 0 |
| Second unchanged | 0 / 0 | 0 / 0 |
| Change a Unicode control alias | 2 / 1 | 2 / 1 |
| Repeat after the edit | 0 / 0 | 0 / 0 |
| Restore the alias and repair the invalid build script | 2 / 1 | 2 / 1 |

Twenty-eight compiled native probes checked the actual library lookup. Each updated alias matched an independently clean build, and all three generated source files agreed. Invalid build script source produced `E0425` in all four arms. The kernel counts cover the project build. Each separate verifying probe ran afterward.

Run `python3 -IB verify.py` here to reopen the original success/error Cargo streams, execve events, native program returns and source hashes. The original source-bound workflow built the Cargo from both exact Git parents, with a signed compiler and Cargo. [Source builder and raw artifacts](https://github.com/astral-experiments/ohm/actions/runs/41108155677)
