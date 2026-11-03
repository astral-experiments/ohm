# Ruff upgrade from signed Ohm -23

On the first unchanged Ruff check after upgrading from signed -23 Cargo to 4a6de785, rustc ran 341 times. The same command immediately afterward ran only ty_python_semantic. The next unchanged check with JSON reporting also ran that one compiler. The project source, paths, target, dependency builds and signed d57fd1515 rustc stayed in place during each Cargo swap.

| Incoming Cargo | Independent cold | Prior unchanged | First unchanged after upgrade | Next unchanged |
|---|---:|---:|---:|---:|
| Signed -23, 7024b0d2 | 366 | 1 | 341 | 1 |
| Earlier v4 fix, ba07041c | 366 | 1 | 35 | 1 |

Cold included 360 Cargo compilation units, five autocfg rustc probes and one Cargo toolchain probe. The first signed upgrade ran 336 Cargo units and the same five kinds of autocfg probes. Of the 360 binary dep-info paths, 32 changed from v4 to v5, two from v2 to v5, and 326 stayed v2. In the earlier-fix upgrade, 34 of the same 360 records changed from v4 to v5 and 326 stayed v2. All 35 rustcs on that upgrade compiled actual Cargo units.

For 270 of the 336 signed-upgrade units the only change from that same history's initial rustc arguments was the two-token option `-Z checksum-hash-algorithm=blake3`. For 42 the arguments were identical, and for 24 the only difference was `-Zthreads=1`. In the earlier-fix upgrade the counts were 11 identical and 24 with that thread option. For any given unit this comparison establishes exactly which arguments reached the compiler. Multiple dependencies can require that unit to build.

The separate real Ruff source edit ran seven compilers across signed -23, matched 7024b0d2, and the fixed 4a6de785. Each subsequent unchanged check ran one of the six units Cargo marked nonfresh, ty_python_semantic. A private-body edit with a stable ruff_linter public hash really compiled ruff_linter and ty_python_semantic. Every invalid check immediately returned E0308 and its repair succeeded. The repair's dedicated cross-upgrade tests are in the parent directory.

The fully independent clean public-header oracle refused signed -23 and the fixed Cargo here. Across those two roles the stable 38,075-definition linter roster and expansion rows agreed, while 28,297 definition results and 15 required crate hashes differed between the warm and entirely rebuilt external dependency environments. This includes get_size_derive2 and get_size2. The same prior experiment found these differences only with matched 7024b0d2. Here that matched parent passed all four independent public-header comparisons. The earlier-fix v4→v5 upgrade kept all four incoming headers across the conversion. This run establishes real compilation rosters, migration cost and diagnostics. Its refused comparisons and absent hardware counter exclude it from performance qualification. The shared-external-input experiment separately enrolls independent empty workspace outputs.

## Reopen the original

The retained 1,824,392-byte compressed input holds the unchanged original kernel exec traces for both complete upgrade histories, and the original phase records and noncold traces for all three ordinary toolchains. SHA-256 is `f9dc999fdea31c399150995a1be7ccc8b10e4b0e1457f7c6b637dc87a0682c03`. The independent reader checks actual decoded rustc argv, diagnostics, headers, six nominally dirty units, both fingerprint inventories and the exact source/ELF bindings.

Run `python3 -IB reopen.py` in this directory. Supplying `--original /path/to/original.zip` verifies all 191,509,985 bytes (SHA-256 `a5a390f0f430c15209d44794cbb8358e6a540992822c3d9dbea26eb54a200172`), both release Cargo ELF bodies, the pre-reader binary, and every selected original member. Supplying `--output /tmp/upgrade-verdict.json` also emits the complete per-rustc argument comparison. The physically rebuilt Cargo versions and their source bindings are included in `release-factories.json` in the original. [Workflow and authenticated artifact 13217478384](https://github.com/astral-experiments/ohm/actions/runs/41606683189).
