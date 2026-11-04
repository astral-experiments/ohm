# Release-trained rustc on Ruff’s Unicode normalization dependency edit

Across six new Linux boots, the release-trained C7 compiler used **25.39% fewer retired user instructions** than C5 for the edited Unicode normalization crate. The complete ordinary Ruff parser check used **2.30% fewer**. The registered decision was **pass**. [Six original workers](https://github.com/astral-experiments/ohm/actions/runs/41853224848) · [Preregistered gates](https://github.com/astral-experiments/ohm/blob/f201e063c87c162547afc85fb0f3f2bf25927703/scripts/ruff-normalization-price/registration.json)

Ruff #21229 updated the locked crate from 0.1.24 to 0.1.25 (4776a20c to c7d0c573). C5 (6c2874a0, #353) and C7 (06fe634f, #355) used the same released -24 Cargo and Wild. Each physical rustc used its own four training profiles under the same release PGO, ThinLTO and BOLT recipe. The true crate count covers the one physical rustc and its own threads, from exec to exit. A separate untraced invocation measured every descendant of the complete `cargo +ohm check -p ruff_python_parser --lib --locked --offline` command. [C5 source factory](https://github.com/astral-experiments/ohm/actions/runs/41742694783) · [C7 source factory](https://github.com/astral-experiments/ohm/actions/runs/41756960897)

| Block | Order | C5 rustc | C7 rustc | Fewer | C5 whole check | C7 whole check | Fewer |
|---|---|---:|---:|---:|---:|---:|---:|
| B1 | C7 → C5 | 1,291,896,606 | 967,781,320 | 25.088% | 14,114,419,728 | 13,790,469,774 | 2.295% |
| B2 | C5 → C7 | 1,294,180,729 | 965,063,631 | 25.431% | 14,111,954,037 | 13,786,052,819 | 2.309% |
| B3 | C5 → C7 | 1,292,750,580 | 964,018,980 | 25.429% | 14,113,694,093 | 13,789,172,294 | 2.299% |
| B4 | C7 → C5 | 1,294,423,259 | 966,392,004 | 25.342% | 14,117,176,265 | 13,785,847,074 | 2.347% |
| B5 | C5 → C7 | 1,296,090,629 | 966,273,289 | 25.447% | 14,122,680,882 | 13,797,871,880 | 2.300% |
| B6 | C7 → C5 | 1,292,587,187 | 965,927,172 | 25.272% | 14,115,965,799 | 13,786,227,446 | 2.336% |

The observed paired savings were 25.3854% (25.0883% to 25.4471%) for the compiler and 2.3047% (2.2952% to 2.3470%) for the complete check. For the prespecified compiler endpoint, the exact paired sign test was 6/6 favorable, two-sided p=0.03125, one-sided p=0.015625. For the complete check it was 6/6 favorable, two-sided p=0.03125, one-sided p=0.015625. The sign test counts the directions of the six within-boot differences. Three boots ran each order. [Original counter records and individual estimates](qualified.json) · [Independent counter calculation](independent_counter.json)

## Cold, settled and build controls

Each median is across the registered six hosts. Positive savings denote fewer C7 instructions. The common guard rejects a paired-median increase exceeding both 2% and 10 million instructions. The separate repaired observations and ordinary build edit are reported alongside the guards.

| Mode | Phase | C5 median | C7 median | Median saved | Minimum saved | Maximum saved |
|---|---|---:|---:|---:|---:|---:|
| build | cold-old | 187,110,006,276 | 186,435,294,838 | 0.3639% | 0.3510% | 0.3969% |
| build | empty-new | 187,131,191,318 | 186,434,308,938 | 0.3671% | 0.3539% | 0.3883% |
| build | ordinary-edit | 63,434,728,806 | 63,110,640,088 | 0.5220% | 0.4800% | 0.5901% |
| build | repaired | 1,232,589,408 | 1,232,088,670 | 0.0356% | 0.0246% | 0.0842% |
| build | unchanged | 210,294,144 | 210,306,446 | 0.0017% | -0.0603% | 0.0189% |
| check | cold-old | 112,129,507,104 | 111,448,985,906 | 0.6138% | 0.5866% | 0.6215% |
| check | empty-new | 112,139,637,249 | 111,455,294,030 | 0.6154% | 0.6040% | 0.6267% |
| check | observed-empty-new-rustc | 1,283,776,758 | 960,359,218 | 25.1915% | 25.1852% | 25.1976% |
| check | repaired | 972,644,072 | 972,548,646 | 0.0083% | 0.0010% | 0.0287% |
| check | unchanged | 208,751,371 | 208,775,493 | -0.0196% | -0.0615% | 0.0588% |

## What ran and what matched

* **C5.** The four individually observed compiler medians were ruff_python_ast 9.377B, ruff_python_parser 2.582B, ruff_python_trivia 0.347B, unicode_normalization 1.293B. The edited unicode-normalization products occupied .rmeta 1,455,983 bytes in check and .rlib 209,324 bytes, .rmeta 1,701,075 bytes in build. The downstream parser's edited and independently empty outputs differed in 4/6 for check .rmeta, 6/6 for build .rlib, 5/6 for build .rmeta.
* **C7.** The four individually observed compiler medians were ruff_python_ast 9.376B, ruff_python_parser 2.583B, ruff_python_trivia 0.349B, unicode_normalization 0.966B. The edited unicode-normalization products occupied .rmeta 469,116 bytes in check and .rlib 209,324 bytes, .rmeta 714,203 bytes in build. The downstream parser's edited and independently empty outputs differed in 6/6 for check .rmeta, 6/6 for build .rlib, 4/6 for build .rmeta.
* The selected physical rustc argv contained 52 arguments in every arm. In all six blocks, the four differences were the output, search and external-library paths containing Cargo’s actual compiler-specific registry shard. [All literal arguments and physical counters](attribution.json)
* Each role had 96 cold products, four edited compilers and zero dirty products on the next unchanged command. Each staged registry source was checked against its locked original. The edited, settled, repaired and independently empty Unicode crate products and complete native observer ELF agreed within each installation. Edited observer ELFs matched byte-for-byte across roles in 0/6 paired blocks.
* The reader executed every SHA-distinct original observer, emitted all 1,112,064 Unicode scalar records and six real Ruff parser verdicts, and recovered just U+A7F1's new NFKC result S. The private overflow failed twice in each of check and build at the identical five-byte span, then repaired to the independent native verdict. The stage1/source study separately examined the downstream parser metadata and target layouts. [Per-owner physical argv and prices](attribution.json) · [Separate metadata and native target controls](https://github.com/astral-experiments/ohm/blob/7856f60de130e8cdd87f797394e3463bbfc68cbe/scripts/ruff-normalization-price/evidence/target-layout/README.md)

The six release-trained worker archives contain 202,151,109 bytes. A 50,030,886-byte portable store reconstructs them byte-for-byte, including their original GitHub ZIP framing. Their official archive digests, the signed SDK identities, every native program, original Cargo stream and hardware journal are retained. The two stage1 pilots and six independent stage1 pairs appear in their original cohort. [Stage1 results](https://github.com/astral-experiments/ohm/blob/563b59e7c41a451d619cd406e9a1972f86797f0d/scripts/ruff-normalization-price/evidence/RESULTS.md)

The verifier also refused eight mutations to genuine ownership, counter, argument and diagnostic records, plus changes to compressed bytes and substitution of a different genuine ZIP. [Raw corruption controls](independent-corruptions.json) · [Archive corruption controls](archive-corruptions.json)

## Reopen the complete registered evidence on Linux

The example uses Python 3.11+, zstd and Linux x86-64 to execute the native observers. Run it from this checkout. The archive digests and official job records are included locally.

~~~sh
set -eu
suite=scripts/ruff-normalization-price
out=$(mktemp -d)
python3 -IB "$suite/evidence/zip_store.py" restore "$suite/evidence/raw" trained-confirmation "$out"
python3 -IB "$suite/review.py" trained-confirmation "$out" --head a7745c51c3035b83c6271c8f037e8a793234d766 --out "$out/result.json"
cmp "$out/result.json" "$suite/evidence/qualified.json"
python3 -IB "$suite/evidence/attribution.py" "$out" "$out/result.json" "$out/attribution.json"
cmp "$out/attribution.json" "$suite/evidence/attribution.json"
python3 -ISB "$suite/evidence/independent_counter.py" "$out" "$out/result.json" "$out/counter.json"
cmp "$out/counter.json" "$suite/evidence/independent_counter.json"
~~~
