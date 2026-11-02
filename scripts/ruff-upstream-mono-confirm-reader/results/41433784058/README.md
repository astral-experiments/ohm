# Six whole-Cargo builds after a real Ruff AST edit

The candidate reduced retired instructions for the complete edited `cargo build -p ruff --bin ruff` by **21.4822%** at the median of six paired independent boots. All six improved. The exact 96.875% median interval is **21.4532% to 21.4922%**, with a two-sided exact sign-test p-value of 0.03125. Each boot built both compilers' arms in the indicated order. [Source run](https://github.com/astral-experiments/ohm/actions/runs/41433784058) · [Independent native and hardware verification](https://github.com/astral-experiments/ohm/actions/runs/41437660060)

| Rank | Order | Parent instructions | Candidate instructions | Reduction | Original native archive |
|---:|:---:|---:|---:|---:|---|
| 0 | PC | 726,203,852,303 | 570,126,891,512 | 21.4922% | [13135843168](https://github.com/astral-experiments/ohm/actions/runs/41433784058/artifacts/13135843168) |
| 1 | CP | 726,168,535,613 | 570,261,975,750 | 21.4697% | [13135699246](https://github.com/astral-experiments/ohm/actions/runs/41433784058/artifacts/13135699246) |
| 2 | PC | 726,147,391,467 | 570,365,618,526 | 21.4532% | [13135774955](https://github.com/astral-experiments/ohm/actions/runs/41433784058/artifacts/13135774955) |
| 3 | CP | 726,105,945,459 | 570,085,912,627 | 21.4872% | [13136556838](https://github.com/astral-experiments/ohm/actions/runs/41433784058/artifacts/13136556838) |
| 4 | PC | 726,268,243,120 | 570,243,549,905 | 21.4831% | [13135913858](https://github.com/astral-experiments/ohm/actions/runs/41433784058/artifacts/13135913858) |
| 5 | CP | 726,204,863,892 | 570,205,926,240 | 21.4814% | [13137825652](https://github.com/astral-experiments/ohm/actions/runs/41433784058/artifacts/13137825652) |

Cold builds used **0.0405% more instructions** at the median, and unchanged builds used **0.0187% fewer**. The edited state used 1.69–1.88 MiB more allocated storage and the same number of files. On every boot, native object reuse rose from 83 to 122 of 124 workspace objects and from 12 to 15 of 256 linter objects. Both unchanged objects and genuinely rebuilt objects remain in the named rosters. The four clean references and all eight ordinary successful visits per boot retained the signed dependency layout of 239 shared and 35 private registry archives.

The independent reader verified all 920,292,329 original ZIP bytes, clean native references, actual edited Ruff verdicts, typed E0308 and repaired outputs. All ten cross-boot parent ELF comparisons required the verified jemalloc debug-directory equivalence. Separate range reads retrieved the six boot identities, both original object ledgers and all six phase/arm clocks from each boot. [Aggregate archive](https://github.com/astral-experiments/ohm/actions/runs/41437660060/artifacts/13137152125)

The clock packet records the measured parent `a3fc6da13921586bc374586dee00883e9210aecd` and candidate `259ad7069e47eaf08cf106f187b2b6393f7fd7c2`. A separate compiletest receipt exercises the two regression-test files added by `6f0191753a5058a8cd2be8ca8ced980e968c7c92`. The candidate and test-only commit share compiler tree `d0262da6fe48ab665147e0e12014d92574897bdc`. The parent failed the intended reuse assertions, and the candidate passed the suite.

From this repository, the following verifies the source hashes of the 36 original hardware records, the twelve named native-object ledgers and the complete paired inference. The packet also preserves the GitHub artifact IDs, byte lengths and full SHA-256 hashes. [Reader and rerun instructions](../../README.md)

```sh
python3 -IB scripts/ruff-upstream-mono-confirm-reader/results/41433784058/verify.py
```
