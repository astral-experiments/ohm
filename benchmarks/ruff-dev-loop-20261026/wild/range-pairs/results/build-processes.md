# Formatter build process counts

The held-out eight-file formatter change rebuilt 19 Cargo units. Every measured command started one Cargo, 19 rustc, eight Clang and eight Wild processes. Here the arithmetic mean of each baseline-minus-candidate difference expresses millions of guest instructions across 12 matched command pairs. Each row sums across the four process roles. The main report uses paired geometric effects and the registered randomization test.

| Baseline | Cargo (M) | rustc (M) | Clang (M) | Wild (M) | Whole command (M) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Wild #42 | 0.1 | -526.4 | 0.0 | 515.6 | -10.6 |
| Ohm #185 | 0.1 | -528.7 | 0.0 | 2,682.1 | 2,153.5 |

Within each edit direction, all 18 measurements used identical sets of 19 complete rustc argument vectors. Per-process records retain each rustc argument digest. [Raw command counts](build.csv), [actual process counts and digests](build-processes.jsonl)
