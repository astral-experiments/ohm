# A release-optimized rustc retained the Ruff CLI build improvement

Each compiler was built separately with the Ohm 1.99.0-24 Linux stage2 recipe, including native profile training, ThinLTO and BOLT. Both used the same signed Cargo and Wild. The only Rust source change under comparison is the derived-method CGU placement and its incremental format version. One paired Linux worker per edit ran the ordinary `cargo +ohm build -p ruff --bin ruff`. Its counter includes the whole inherited user-mode process tree. A separately initialized history on the same worker counted the same complete command and each actual compiler process.

| Historical source edit | P → C whole command | Fewer instructions | Independent edit history | Fewer in the Ruff library rustc |
|---|---:|---:|---:|---:|
| Correct the `--config` help example (#28392, PC) | 17,383,345,108 → 10,504,286,837 | 39.573% | 39.606% | 49.959% |
| Add `ruff format --extend-exclude` (#26372, CP) | 10,739,694,617 → 10,083,659,664 | 6.109% | 6.129% | 11.086% |

On the help edit the measured library rustc fell from 13,805,530,192 to 6,908,453,256 retired instructions. Four native CGUs needed work under each compiler. Their full object bodies went from 2,289,560 to 1,114,224 bytes. The candidate used 241 units and reused 237 physical donors. The parent used 236 and reused 232. After the edit the candidate occupied 1,880,064 additional allocated bytes across the measured roots. Its cold OLD build used 0.131% more instructions and its fresh NEW build used 0.127% more. All measured unchanged builds ran zero rustcs and links. The second edit added 73,728 allocated bytes.

Both ordinary edits changed the intended CLI behavior. The run exercised invalid and valid configurations, rejected invalid Rust twice, repaired it, and compared the complete edited CLI and its native program bodies to an independent empty target within each compiler. Monomorphization and native ownership checks cover the original selected types and per-source caps of one and two.

Warm and fully empty NEW metadata showed a pre-existing boundary in these independent builds. On #28392 the parent had identical public rows. The candidate differed on 1,139 public rows and 30 required crate hashes, including `get_size_derive2`. On #26372 both compilers differed on 1,117 rows and 27 required crate hashes. The typed metadata sidecars keep every changed requirement and the separate repair and repeated-history results. The physically matched complete CLI and its functional verdicts are independent of those metadata differences.

The separate six-host study uses source-matched stage1 compilers. Its median whole-command reduction was 36.944% on #28392. It provides the repeated hardware result. The two trained pairs here provide a separate check using the actual native compiler build recipe. [Six independent hosts](https://github.com/astral-experiments/ohm/blob/b6ec5d8206e912b721696cf2db2220ca975423b8/scripts/ruff-derived-impl-cgus/evidence-confirmed-28392/README.md) · [Parent training](https://github.com/astral-experiments/ohm/actions/runs/41737296261) · [Candidate training](https://github.com/astral-experiments/ohm/actions/runs/41738530557) · [Ordinary builds](https://github.com/astral-experiments/ohm/actions/runs/41746716369) · [Independent complete-object reader](https://github.com/astral-experiments/ohm/actions/runs/41751651690)

To reopen the permanent packet, run from the repository root with Python 3.11+, `zstd`, and GNU binutils available.

```sh
python3 -IB scripts/ruff-derived-impl-cgus/evidence-release-optimized/verify.py
```

`checked-originals.zip` is the unmodified 5,035,356-byte reader artifact. The verifier checks every ordinary hardware record, the original per-process kernel counter streams, unchanged rosters, the original native code for edited CGUs, and the hosted artifact bindings. The two full producer archives additionally contain the complete executables and all physical donor bodies.
