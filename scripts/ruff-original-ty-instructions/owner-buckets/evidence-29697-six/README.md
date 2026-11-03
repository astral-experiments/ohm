# Ruff #29697 e2e test build on six independent Linux boots

Rust #329 reduced retired user instructions for the complete edited e2e test build by **59.61%**, or **2.476×**. Six independent machines each ran one matched pair, three parent-first and three candidate-first. All six speedups fall between 2.4731× and 2.4778×. This range is a 96.875% distribution-free interval for the paired median. The exact two-sided sign test gives p = 0.03125. We excluded the exploratory four-history pilot on a separate boot.

~~~sh
cargo +ohm test -p ty_server --test e2e --no-run --locked --offline -j4 --message-format=json
~~~

| Host | Order | Parent instructions | #329 instructions | Speedup | Retained ty_ide objects out of 171 |
|---:|---|---:|---:|---:|---:|
| 0 | PC | 90,083,784,542 | 36,416,020,549 | 2.47374× | 148 → 171 |
| 1 | CP | 90,046,410,951 | 36,360,394,316 | 2.47650× | 148 → 171 |
| 2 | CP | 90,095,917,745 | 36,361,709,454 | 2.47777× | 148 → 171 |
| 3 | PC | 90,128,982,509 | 36,403,786,849 | 2.47581× | 148 → 171 |
| 4 | PC | 90,057,648,422 | 36,357,401,821 | 2.47701× | 148 → 171 |
| 5 | CP | 90,064,906,940 | 36,418,272,897 | 2.47307× | 148 → 171 |

The edit spans Ruff 157caa55 and bfa2407e. It changes ty_project and ty_server and leaves the ty_ide sources intact. All twelve histories reported the same 289 Cargo units and 200 test names. Both roles emitted E0599 for the new method on OLD and E0308 for invalid source. The held OLD executable failed the changed debugger snapshot. The edited, repaired and independently empty NEW executables passed it. Test execution was outside every counter.

All twelve primary hardware counters had identical enabled and running duration. The separate kernel replay observed four real rustcs and Wild in every edited command and no rustc or Wild on the unchanged command. The observed ty_ide retention agreed with the primary on every history. Two parent process samples, separate from the primary clock, showed a positive interval without active time: 16,683 instructions in ty_ide on host 0 and 15,657 in ty_server on host 1. Across all six boots both roles produced the same whole OLD executable c13ba33d1c3ba67deb363d2ba861f5ef640b2fa33eadd67cad758cd98d4ffc9b. Every edited, repaired and independently empty NEW executable was f0e785ff42ca6227d246a7cb0998af88654c1776c7a595f2f9e97733028c0074. The original-archive reader reopened 192 native or graph bodies and joined every native ty_ide object to its finalized physical session by full SHA-256 and byte size.

The median paired cold cost differed by −0.0043% and unchanged cost by +0.0015%. The medians per role were 2.49109T and 2.49114T cold, and 447.101M and 447.117M unchanged. Median paired settled allocated storage increased 0.4415% (range 0.2407–0.7636%). Per-role median sizes were 2,731,628,544 and 2,743,762,944 bytes. In the earlier pilot the edited ty_ide graph occupied 39,307,678 and 39,437,642 bytes. The complete query and storage counts are in [graph-costs.json](graph-costs.json).

The source-built drivers correspond to the signed −23 Rust parent d57fd151 and the original #329 patch on that base (5c5af1a0, patch ID 30c8ceaa86486b1fc7d77ca44845ba577eee4dcd). Both roles use the same signed Cargo 7024b0d2, LLVM and Wild. The original signed −23 edit measured 67.256B instructions on a separate worker. The six prices here compare the two matched source builds, which have different optimization profiles from signed release binaries.

The original signed graph and native ELF identified two coarse upstream Vec queries. Of 23 regenerated ty_ide objects, 21 had only upstream_monomorphizations_for changed among their serialized direct fingerprints. The actual executable showed two true Vec<File> monomorphizations moving to ty_project from ty_server. #329 recovered all 23 original ty_ide objects and preserved the new native providers. The signed graph establishes the direct dependency for 21 cases; first-red callbacks for the other two are unavailable.

## Review and rerun

[Six fresh workers](https://github.com/astral-experiments/ohm/actions/runs/41628659619) · [two-order pilot](https://github.com/astral-experiments/ohm/actions/runs/41626063521) · [Rust #329](https://github.com/astral-experiments/ohm-rust/pull/329) · [frozen protocol](https://github.com/astral-experiments/ohm/tree/49f33a6fcd94d15b1cc5e442315613aed1b8cafe/scripts/ruff-original-ty-instructions/owner-buckets) · [signed profiles and actual native providers](https://github.com/astral-experiments/ohm/tree/49f33a6fcd94d15b1cc5e442315613aed1b8cafe/scripts/ruff-original-ty-instructions/source-pcs/verified-29697)

These exact raw hardware, donor, kernel-argv and verdict records can be inspected directly from the packaging checkout. The 1,272 original records deduplicate to 972 payloads. The compact 1,124,629-byte archive covers 51,515,217 unique source bytes.

~~~sh
v=scripts/ruff-original-ty-instructions/owner-buckets
e="$v/evidence-29697-six"
python3 -IB "$v/read_compact.py" "$e/controls.tar.zst" --sha256 831d23b8cf60cfad585e7baec93f208a9b5de102a5bd63551e5f655a666d5e0a
~~~

To authenticate all original native ELF, ar, graph and counter bytes use an output directory with at least 16 GiB free plus the archive space, zstd and GNU binutils.

~~~sh
raw=$(mktemp -d)
jq -r '.assets[] | [.name,.id] | @tsv' "$e/assets.json" |
  while read -r name id; do
    slot=$(printf '%s' "$name" | awk -F- '{print $NF}')
    gh-auto api "repos/astral-experiments/ohm/actions/artifacts/$id/zip" > "$raw/$slot.zip"
  done
python3 -IB "$v/confirm.py" "$raw" --assets "$e/assets.json" --output "$raw/reopened.json"
cmp "$raw/reopened.json" "$e/fully-reopened.json"
~~~
