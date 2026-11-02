# Matching ordinary post-O1 LLVM input on Ruff #28106

This component experiment measures a real Ruff option edit on x86-64 Linux. The parent of the experimental rustc is `531eb1980c08c75ccbf3f6b77adbee53cd9b8bd5` and the candidate is `4e546b27c311f29d99f9528e64420887f57c7538`. Its LLVM wrapper hashes the actual module passed to machine code generation. It leaves the ordinary optimizer and its inputs alone. The normal Cargo owner used opt-level 1, incremental compilation, line-tables-only debug info, no LTO and no embedded bitcode. [Candidate compiler source](https://github.com/astral-experiments/ohm-rust/blob/4e546b27c311f29d99f9528e64420887f57c7538/compiler/rustc_llvm/llvm-wrapper/OhmSourcePlacement.cpp)

The capture contains 21 old and 21 new before-optimization modules from the real signed -22 Ruff command. We regenerated all of them with the authenticated signed LLVM module optimizer and called the real candidate wrapper in the same process, before serializing the optimized module. The new optimized byte streams also match 21 earlier independently reproduced signed outputs. Neither set is presented as a rustc-owned post-optimization dump. When we serialized each live module and reparsed its bitcode, its full key changed on all 42. Both measurement roles use the same live boundary. The same 16 pairs matched at either boundary, and the old captured native object plus the two live records produced the exact warm and independently empty edited object on all 16. [Native object and hostile-input verification](https://github.com/astral-experiments/ohm/blob/91e0e543ecb156f8ebe21b2001cf2a77c2f02a7a/scripts/ruff-cgu-debug-locations/evidence/41371190920/native/post-o1-live.md)

| Component | Callgrind 3.22.0 guest instructions |
|---|---:|
| Original fixed LLVM backend, 21 edited units | 120,906,271,208 |
| Machine code generation for the 16 accepted units | 60,436,240,766 |
| Compute the actual C2 key and current source positions on all 21 | 8,909,198,327 |
| Native object rewrite or refusal on all 21 | 373,925,640 |
| Remaining original backend plus both replacement components | 69,753,154,409 |
| Parse serialized optimized modules, separate counterfactual | 3,109,017,091 |

The resulting **1.7333×** is a projection for this fixed set of backend units. It includes normal O1. The semantic prepass in the discarded original prototype incorrectly equated allocations whose authentic native programs return 16 and 32; C2 distinguishes both cases after normal O1. The real wrapper also rejects debug-location operands reachable from LLVM loop metadata. Debug normalization before O1 without semantic transformations matched 6/21 and covered 10,155,011,840 original backend instructions. The C2 figure excludes other compiler phases, Cargo, linkers, disk persistence, and observed end-to-end time.

Each producer profile charged the bounded callback and releasing its returned wire on the live optimized input. Cloning cost 1,877,932,175, verifying the LLVM modules cost 2,034,444,675, streaming bitcode into SHA-256 cost 3,183,165,886, and destroying the clone cost 261,654,240. The rest includes collecting/normalizing the debug graph, emitting its source-position wire and callback ownership. The compiler already has this module in memory. Loading, parsing the initial bitcode, and normal O1 occur before the producer counter starts. They remain part of the original workload. The independent parser-only acquisition counts decoding an already optimized serialized module, with no producer charge during that region.

The first continuous-live 21 profiles and three reverse repetitions passed their registered exact-count checks. In a separate experiment pricing reparsed inputs, the original procedure varied an otherwise unused command-line label between repetitions and produced small differences. That counter population was excluded. We repeated the full live and parser cohorts with the same argv, fd numbers, binaries and ordering on each repetition, altering only the external profile destination. All six repeats reproduced exactly, as did all 21 live costs across the two complete acquisitions. The portable raw profiles retain inclusive and exclusive function costs; only local directory prefixes in the text headers and object names are replaced. The manifest binds both the original raw bytes and their public projections.

## Reopen or reproduce

```sh
python3 -IB verify.py
```

To execute the real producer, provide the signed Ohm -22 Linux x86_64 LLVM shared library, matching LLVM 23 headers, Valgrind development headers, the candidate Rust checkout above, and the ordinary signed #28106 input ZIP (artifact 13109144871 of run 41371190920, SHA-256 `53ede61bc14ac8e524813b6cac9d1cfbbcd595b5380fae363e681406aa7b404b`). `build.sh` verifies the LLVM and source by SHA. `replay.py` verifies the complete original archive, each actual input and each resulting candidate key and wire length.

```sh
LLVM_CONFIG=/path/to/matching/llvm-config SIGNED_LLVM=/path/to/signed/libLLVM.so.23.1-rust-1.99.0-beta \
  RUST_SOURCE=/path/to/4e546b27 OUT=/tmp/ruff-post-o1-tools sh build.sh
python3 -IB replay.py --originals /path/to/ordinary-signed-originals.zip \
  --tools /tmp/ruff-post-o1-tools --all-units
```
