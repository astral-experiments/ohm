# Reconstructing 16 Ruff objects after ordinary LLVM optimization

The second prototype reconstructed 16 of the 21 `ruff_workspace` objects rebuilt by Ruff #28106. Twelve required different bytes. Every output matched both the original edited build and an independent build from an empty target directory. Reverse reconstruction matched the previous build. The five remaining units fell back in both directions. This replay compares complete native ELF objects, including code, data, relocations, symbols and debug information. [Original ordinary Ruff run](https://github.com/astral-experiments/ohm/actions/runs/41371190920)

The compiler computes a SHA-256 commitment to the normalized module and a source-coordinate record after its usual LLVM O1 pipeline. It takes both records directly from live modules. All 42 commitments differed when the exact same optimized bitcode was reparsed, although the 42 source-placement records and all 21 admission decisions agreed across domains. This study passed the original 42 *live* records to the exact Rust rewriter and reopened all 63 native objects. The 21 previous records add 111,777 bytes alongside 14,348,624 bytes of native objects (0.78%). The 16 previous records admitted here occupy 76,627 bytes.

The earlier prototype normalized IR before normal optimization and could erase a real allocation-size distinction. Four linked tests returned 16 where the current build returned 32 or the reverse. Those failures rule out the earlier design. [Rejected prototype and literal raw checks](README.md) · [Allocation source and linked behavior](https://github.com/astral-experiments/ohm/blob/9191b98b31043b424badbd7090354bec62b5d661/scripts/ruff-placement-allocsize/README.md)

## Fixed-input instruction counts

| Component | Valgrind 3.22 guest instructions |
| --- | ---: |
| Ordinary LLVM optimization and machine emission across 21 units | 120,906,271,208 |
| Original machine emission in the 16 recovered units | 60,436,240,766 |
| Construct and validate live optimized IR commitments and placements on all 21 units | 8,909,198,327 |
| Read the previous ELF and both records, reconstruct or decline, write and free the result on all 21 units | 373,925,640 |
| Remaining ordinary work plus the two new components | 69,753,154,409 |

The fixed-input estimate is **1.733×** across these 21 units. The compiler already paid for O1 in every case. A complete `cargo build` also includes frontend work, incremental state and linking. Whole-command hardware counters are a separate experiment.

The 16 successful native calls spent 373,903,397 guest instructions and emitted 9,211,992 bytes. The five fallbacks spent 22,243 and emitted zero bytes. The three preselected inverse-order repetitions reproduced the original printed counts exactly. Both empty regions retired 23 guest instructions. An earlier collector tried to read a removed classification field after running the empty marker. Its empty marker, both enrollments and all 26 new raw regions are preserved. The registered unit roster, order, native implementation, physical oracle and exact callback bytes stayed the same.

## Adversarial coordinates on real Ruff modules

We selected three real modules by their original native size and registered 12 source-coordinate perturbations for each. Two patterns were absent on the smallest input, leaving 34 real old/new pairs. Twenty-four pairs produced different native bytes in ordinary LLVM. The changes covered adjacent source rows, multiple files, mixed inline chains, large positive deltas, integer-width boundaries, equal lines across files, ordering inversions, zero and one, and a genuine column change. The ordinary backend generated both inputs’ native objects at least twice across the independent trials. These component emits use the signed LLVM 23 target configuration. For each of the three original modules, the standalone output differed from the entire rustc driver's archived object. The separate unmodified Ruff trial above uses the original compiler objects.

All 68 same-input identity checks passed. In both the live and reparsed domains, 40 old/new directional reconstructions reproduced *every byte* of the freshly emitted ELF. Twenty-eight directions declined. Ten of the 20 admitted pairs required a physical change. Three admissions that previously declined (one cross-file case and two order inversions) had identical clean objects. Allocated bytes, symbol registries and resolved relocations agreed on all 34 pairs. The raw cases preserve both signed ordinary object hashes and the result or refusal for each direction. A separate two-file example verifies an observable debugger difference when a source-line relationship crosses file boundaries. [Signed GDB control](https://github.com/astral-experiments/ohm/blob/28f2ad253a6252632ba3a8a64dfe109a61fd99e4/scripts/ruff-cross-file-line-order/README.md)

## Reproduce

`verify_live.py` reads the two compact packets in this directory. It directly joins each measured count to its complete literal callback, prior/edited/empty object identity and exact native verdict. It reopens every raw counter and every registered hostile case.

```sh
python3 -IB verify_live.py
```

To repeat all 84 physical verdicts and all 26 native counter regions, export and compile the exact second Rust implementation and supply the original ZIP (artifact `13109144871`, full SHA-256 `53ede61bc14ac8e524813b6cac9d1cfbbcd595b5380fae363e681406aa7b404b`). Use Linux x86-64 with the declared Valgrind version and development headers.

```sh
work=$(mktemp -d)
python3 -IB verify.py --post-o1-harness "$work/source"
CARGO_TARGET_DIR="$work/target" CARGO_BUILD_BUILD_DIR="$work/build" \
  cargo +ohm build --locked --release --jobs 1 --features qa-counter \
  --manifest-path "$work/source/Cargo.toml"
python3 -IB verify_live.py --original /path/to/ordinary-13109144871.zip \
  --actor "$work/target/release/ohm-dwarf-coordinate-qa" --recount
```

The public reader reopened all 63 original members, re-executed the 84 live native checks and exactly reproduced all 26 counter regions on the enrolled physical actor. [Rerun receipt](post-o1-repeat.json)
