# Local function binding in the source-built Ohm rustc driver on uv #21577

After the landed edit to uv, the terminal `uv_warnings` compiler retired **21.703 and 21.704 percent fewer instructions** on the two hosts against shipped Ohm −23. Against an independent production rebuild of the same release, reductions were **21.706 and 21.702 percent**.

The ordinary Cargo command had paired median wall speedups of 1.000 and 1.016 times against the shipped release and 1.206 and 1.013 times against the matched rebuild. There were 0/16 pairs at 2× against the shipped release and 0/16 against the rebuild.

The preregistered terminal gate required a reduction of at least 20% in every pair against each baseline, including both halves on each host. The separate whole-command gate required a wall speedup of at least 2× on the same comparisons. The terminal gate passed and the wall gate missed.

| Median paired reduction | Shipped → patched, host 1 | Host 2 | Rebuild → patched, host 1 | Host 2 | Shipped → rebuild, host 1 | Host 2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Terminal uv_warnings rustc | 21.703% | 21.704% | 21.706% | 21.702% | -0.001% | -0.001% |
| uv_errors rustc | 5.677% | 5.680% | 5.681% | 5.677% | -0.001% | 0.004% |
| Both rustcs | 9.006% | 9.010% | 9.010% | 9.007% | -0.001% | 0.003% |
| Whole Cargo instructions | 5.496% | 5.498% | 5.497% | 5.498% | -0.001% | 0.000% |
| Whole Cargo blocking wall | -0.029% | 1.554% | 17.060% | 1.332% | -9.125% | 2.420% |

Each host ran eight counterbalanced three-compiler blocks of `cargo check -p uv-warnings --lib --locked --offline -j8`. Every visit started from its own ordinary cold pre-edit target. The native edited invocation ran exactly two rustcs. The inherited whole-process counter, the two kernel-bound per-rustc events and the unwrapped blocking wall each ran on separate restorations. [Landed uv change](https://github.com/astral-sh/uv/pull/21577)

Both source-built compilers used the −23 GNU release PGO, ThinLTO and BOLT recipe. All roles used the same signed Cargo. The change keeps exported symbols visible and binds references from within the driver to eligible strong compiler-owned Rust functions. The direct external caller and foreign interposition checks are in the mechanism records. [Control build](https://github.com/astral-experiments/ohm/actions/runs/41615634254) · [Corrected compiler build](https://github.com/astral-experiments/ohm/actions/runs/41640655120)

An earlier source build verified local ELF binding but failed native saved-link replay and GNU ld fallback. It supplied no hardware performance samples. The measured source restricts the private link options to the bundled linker and leaves replay and GNU ld on their ordinary semantics. [Earlier mechanism build](https://github.com/astral-experiments/ohm/actions/runs/41619498528)

The rebuilt and shipped controls produced identical bytes at all 39 metadata paths and all 30 public hash sidecars before and after the edit. Different rustc commit versions alter stable crate identities. Across compiler versions we compared all 39 native item interfaces and bound each sidecar to its producing crate. Each role separately matched its independently cold edited build byte for byte. All roles reproduced the linked before-and-after warning behavior and the zero-compiler unchanged checks.

Run `python3 -ISB verify.py` to reopen both original hardware archives offline and recompute every pair. The script checks the 54 native visits across both hosts before scoring. It also reopens the source builds’ shared ELF correspondence and the actual preload outcomes. [Frozen worker](https://github.com/astral-experiments/ohm/tree/294569f5daebcdd802ac0bcf7c7ea32dc3e3149e/scripts/driver-bind-21577) · [First host](https://github.com/astral-experiments/ohm/actions/runs/41648707018) · [Independent host](https://github.com/astral-experiments/ohm/actions/runs/41648918827)
