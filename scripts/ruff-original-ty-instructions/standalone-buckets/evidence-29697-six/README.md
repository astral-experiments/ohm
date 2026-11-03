# Ruff #29697 ordinary ty_ide library build

Rust #329 reduced the complete edited library build from a median 43.438 billion to 19.057 billion retired user instructions. The median paired improvement was **2.2791×** on six fresh Linux boots, with 56.12% fewer instructions. The exact distribution-free median interval is 2.278692–2.280316× (96.875% coverage). All six pairs cleared the preregistered 2× gate. The two-sided exact sign-test p-value is 0.03125. The separately reported first pair was excluded. [Rust #329](https://github.com/astral-experiments/ohm-rust/pull/329) · [Six-boot run](https://github.com/astral-experiments/ohm/actions/runs/41660912896) · [First pair](../evidence-29697-first/README.md) · [Protocol before dispatch](https://github.com/astral-experiments/ohm/blob/6021d694d1c5d2e1a661e19b14d2990e7bb30834/scripts/ruff-original-ty-instructions/standalone-buckets/PROTOCOL.md)

Each fresh boot ran one parent/candidate pair on the real Ruff change from `157caa55` to `bfa2407e`. The source edit gives ty_project a new public method and changes its behavior with uv disabled. The two commands rebuilt the edited ty_project and its source-unchanged ty_ide consumer. The parent regenerated 23 of 171 ty_ide objects on every edit. The candidate kept all 171 while producing the changed interface. A separate traced repetition priced ty_ide itself at 28.523 versus 4.180 billion instructions (medians). The resolved graph had 283 nodes and emitted 259 Cargo units. The edit invoked two real rustc processes and zero final linkers; the subsequent unchanged command invoked zero of either. Runtime and client links ran outside all hardware counts. [Ruff edit](https://github.com/astral-sh/ruff/commit/bfa2407e98ee1343caeefd02b4b69043509baa8c) · [Actual named query and native owner from the e2e study](https://github.com/astral-experiments/ohm/blob/49f33a6fcd94d15b1cc5e442315613aed1b8cafe/scripts/ruff-original-ty-instructions/source-pcs/verified-29697/README.md)

```sh
cargo +ohm build -p ty_ide --lib --locked --offline -j4 --message-format=json
```

| Boot | Order | Parent instructions | Candidate instructions | Ratio |
|---|---|---:|---:|---:|
| 0 | P, C | 43,438,925,890 | 19,063,093,390 | 2.278692 |
| 1 | C, P | 43,427,053,925 | 19,053,001,332 | 2.279276 |
| 2 | C, P | 43,438,179,573 | 19,058,639,409 | 2.279186 |
| 3 | P, C | 43,428,944,590 | 19,055,981,171 | 2.279019 |
| 4 | P, C | 43,438,494,706 | 19,062,358,521 | 2.278758 |
| 5 | C, P | 43,445,098,324 | 19,052,224,264 | 2.280316 |

| Control | Parent median | Candidate median | Median paired change | Full paired range |
|---|---:|---:|---:|---:|
| Empty OLD build, instructions | 2,097,951,008,164.5 | 2,097,778,074,960 | −0.0083% | −0.0295% to +0.0346% |
| Unchanged NEW build, instructions | 423,172,968.5 | 423,068,060 | −0.0240% | −0.1573% to +0.0481% |
| Settled allocated bytes | 2,216,513,536 | 2,228,891,648 | +0.5599% | +0.4261% to +0.7041% |
| Physical files | 5,120 | 5,120 | 0% | 0% |

Storage covers the worktree target and shared build tree with each physical inode counted once. The median paired incremental dep-graph grew 13.49 MB, while the query-cache shrank 1.07 MB. The 185,098 bytes of work-product tables were identical in size across all 12 observations.

Both source-built kits used the signed −23 Cargo, LLVM and linker. P used the published Rust source `d57fd1515986dccecdcece8da85e651bfb4b81f9`; C used its direct child `5c5af1a053326e6ce5df048c4dcb30b53e01a069`. Every added and removed line matches the original two #329 commits through `6f019175`, byte-for-byte per file, including whitespace. The stable patch ID is `30c8ceaa86486b1fc7d77ca44845ba577eee4dcd`. These costs compare two matched source builds. A future signed release still needs its own qualification. [Source-built factory](https://github.com/astral-experiments/ohm/actions/runs/41624273152) · [Exact source comparison](source-equivalence.json)

## Native and metadata controls

The reader reopened all six original ZIPs (1,509,904,814 bytes), decompressed and authenticated 271 distinct-per-boot physical bodies (6,313,094,663 bytes), and independently ran both complete ELF clients from each original. The old API selected the real script with uv off and on. The changed API selected zero with uv off and one with uv on. Both programs passed three `ty_ide::map_system_to_vendored` checks. The preserved OLD binary kept the old verdict. All edited, repaired and independently empty NEW binaries had the same SHA-256, across both roles and all six boots. The OLD SDK API test reported E0599 and an actual invalid edit reported E0308 in every role. [Client source](../client.rs) · [Per-job native evidence](reopened.json)

Every warm/empty pair matched all 171 ty_ide and 245 ty_project native members by stable filename, complete ELF payload and archive order. The symbol-to-member index matched for all 4,199 and 7,276 symbols respectively, as did the complete late-metadata wrapper after normalizing only the compiler-generated archive-member suffixes. The original names and 4,992 warm/empty member comparisons remain in the raw controls. [Source explanation and four negative controls](../evidence-parent-archive/README.md)

The absolute metadata fingerprints vary with compiler and build history. On the actual edit each role had exactly the same added, removed, and changed key sets across all four decoded tables. In ty_ide, 3,033 public definition rows and one required crate changed; both the stable definition and expansion rows agreed. In ty_project, the edit added two definitions, changed 745 existing def-path descriptions and 4,251 existing public rows, and changed 53 expansions. Warm versus independently empty NEW changed 3,084 public rows, nine expansions and 26 required crates in ty_ide, and 4,276, 46 and 25 in ty_project. Even these warm/empty change sets agreed across the roles. The archives therefore support complete native and runtime equivalence alongside specifically recorded metadata differences. Full archive or absolute public fingerprint equality would be a stronger claim. [Per-role byte-backed readback](reopened.json) · [Metadata reader](../public_states.py)

## Reproduce

From the parent script directory on Linux, read the compact permanent raw hardware, Cargo, process, and native-ledger controls in this Git commit.

```sh
d=evidence-29697-six
python3 -IB read_compact.py "$d/raw-controls.tar.zst" --assets "$d/assets.json" --summary "$d/reopened.json"
```

To independently reparse the emitted rlibs, prove the GNU archive symbol mapping, decode the full metadata, and execute both clients again, fetch the original Actions artifacts during their retention period. Run from an OSS checkout with `gh-auto`, GNU ar, zstd, x86-64 Linux and 18 GiB free. The reader verifies each original SHA-256 before using a body. The six full originals retain their complete bytes for 21 days. The permanent 852,481-byte packet retains 731 deduplicated control streams (43,426,689 raw bytes), including every exact hardware count and every ordered member association; executing the original clients requires the original ZIPs.

```sh
mkdir -p /path/to/ty-ide-originals
python3 -IB fetch.py --assets "$d/assets.json" /path/to/ty-ide-originals
python3 -IB confirm.py /path/to/ty-ide-originals --assets "$d/assets.json" --output /path/to/ty-ide-originals/rechecked.json
cmp "$d/reopened.json" /path/to/ty-ide-originals/rechecked.json
```

The separate six-boot `cargo test --no-run` confirmation measures a different dependency graph and final link. [E2e source and result](https://github.com/astral-experiments/ohm/blob/d2496f094f83dad73c7aa5151ad00a1ae22e9847/scripts/ruff-original-ty-instructions/owner-buckets/evidence-29697-six/README.md)
