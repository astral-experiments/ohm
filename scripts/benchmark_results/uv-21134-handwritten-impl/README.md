# Stable handwritten impl identities on the uv #21134 edit

The candidate used **13.7719% and 13.7759% fewer retired instructions** in the terminal `uv` library compiler on two independent hosts. The bare Cargo check took **8.0389% and 7.4927% less time** by median paired ratio. On each host, 0 of 8 pairs reached the registered 20% terminal-instruction threshold, and 0 of 8 reached 2× on the bare check. The rule required all eight pairs on each host, including each four-pair half. [Original registration](../../uv-check-21134/protocol.json) · [Independent two-host result](replication.json)

The real edit orders equally preferred Python installations by key. Each role ran the first ordinary `cargo check -p uv --lib --locked --offline -j8` after the landed source change `728a70d2` → `a6904bbd`. F is the optimized full-stack compiler on the signed −23 base. G is its direct child with the handwritten-impl identity change. Stock signed −23 failed this command’s warm-versus-independent-cold native gate because the terminal public metadata hash and 4,801 definition fingerprints differed. Only F/G was scored. [Landed uv change](https://github.com/astral-sh/uv/pull/21134) · [Signed-control refusal](../../uv-check-21134/signed-R-native-refusal.json)

## Hardware measurements

Each line shows independent per-host medians. Instruction counts are billions of retired user instructions. The reduction is the median of the eight paired `1 − G/F` values, so it can differ from the percentage computed from the two arm medians. The per-process counter, whole-Cargo counter and bare wall clock used separately restored first-edit visits.

| Endpoint | Host 1931 F | Host 1931 G | Reduction | Host 1937 F | Host 1937 G | Reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Terminal `uv` compiler | 16.4108 | 14.1419 | 13.7719% | 16.4010 | 14.1317 | 13.7759% |
| Sum of 14 rustcs | 33.0914 | 30.5066 | 7.8036% | 33.0784 | 30.4915 | 7.8347% |
| Whole Cargo process tree | 33.9086 | 31.3241 | 7.6161% | 33.8957 | 31.3090 | 7.6458% |
| Bare Cargo wall, seconds | 4.2798 | 3.9501 | 8.0389% | 4.1994 | 3.8739 | 7.4927% |

The median paired time saved was 0.3434 seconds on host 1931 and 0.3138 seconds on host 1937. The repeat’s sixth G visit took 9.298 seconds against 4.215 seconds on F. All observations are included.

| Pair | Host 1931 order | F (s) | G (s) | Host 1937 order | F (s) | G (s) |
| ---: | --- | ---: | ---: | --- | ---: | ---: |
| 1 | F/G | 4.253 | 3.946 | G/F | 4.173 | 3.869 |
| 2 | G/F | 4.286 | 3.954 | F/G | 4.201 | 3.864 |
| 3 | G/F | 4.273 | 3.900 | F/G | 4.198 | 3.838 |
| 4 | F/G | 4.291 | 3.960 | G/F | 4.203 | 3.879 |
| 5 | G/F | 5.543 | 4.145 | F/G | 4.186 | 3.936 |
| 6 | F/G | 6.090 | 3.957 | G/F | 4.215 | 9.298 |
| 7 | F/G | 4.264 | 3.939 | G/F | 4.233 | 3.825 |
| 8 | G/F | 4.258 | 3.903 | F/G | 4.156 | 3.906 |

Each process below is an actual emitting rustc. Counts are millions of instructions. A negative reduction indicates that G used more instructions. [Every raw word, PID, event ID and argv digest](counters.tsv) · [Full per-pair clocks and counters](pairs.tsv)

| Compiler | Host 1931 F | Host 1931 G | Reduction | Host 1937 F | Host 1937 G | Reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `uv` | 16,410.79 | 14,141.86 | +13.772% | 16,401.04 | 14,131.74 | +13.776% |
| `uv_build_frontend` | 512.46 | 521.96 | -2.260% | 508.81 | 512.15 | +0.038% |
| `uv_cli` | 3,684.49 | 3,684.31 | +0.005% | 3,684.58 | 3,684.34 | +0.006% |
| `uv_dispatch` | 437.40 | 437.38 | +0.005% | 437.40 | 437.38 | +0.003% |
| `uv_distribution` | 1,263.39 | 1,224.06 | +3.112% | 1,263.41 | 1,224.08 | +3.113% |
| `uv_installer` | 695.19 | 687.96 | -0.014% | 680.47 | 680.61 | -0.017% |
| `uv_python` | 3,395.98 | 3,106.43 | +8.526% | 3,395.99 | 3,106.43 | +8.526% |
| `uv_requirements` | 442.79 | 443.11 | -0.071% | 442.78 | 443.12 | -0.077% |
| `uv_resolver` | 3,676.09 | 3,675.26 | +0.024% | 3,676.09 | 3,675.28 | +0.022% |
| `uv_scripts` | 295.32 | 295.36 | -0.015% | 295.33 | 295.36 | -0.011% |
| `uv_settings` | 1,442.77 | 1,442.75 | +0.002% | 1,442.77 | 1,442.75 | +0.002% |
| `uv_tool` | 350.59 | 350.62 | -0.008% | 350.57 | 350.62 | -0.019% |
| `uv_types` | 249.27 | 249.33 | -0.026% | 249.27 | 249.33 | -0.022% |
| `uv_virtualenv` | 248.80 | 248.85 | -0.021% | 248.79 | 248.86 | -0.023% |

## Source, population and native checks

The same signed Cargo (`f7cfe387ec3b…`) drove both optimized SDKs. Each installed SDK had 142 files. The artifact and installed content digests are separate. [F production source, SDK, QA and signed Cargo](../../uv-client-22958/signed-23-split-lock.json) · [G source, SDK, QA and two-format migrations](../../uv-check-21134/G-qualified-lock.json)

| Role | Rust source | Incremental / rmeta format | Production SDK Actions artifact |
| --- | --- | --- | --- |
| F | `60bd529e1a0d59e5904912bd38e6a13702d10263` | 43422 / 43422 | [13204300353](https://github.com/astral-experiments/ohm/actions/runs/41572266236/artifacts/13204300353) |
| G | `ef4e1dea0be3c3dcf25b9d3b7c8774098a2cec36` | 43423 / 43423 | [13211807074](https://github.com/astral-experiments/ohm/actions/runs/41590680452/artifacts/13211807074) |

Each host measured eight counterbalanced first-edit pairs, with one newly grown cold A per role and pair. Both roles passed unchanged A/B checks and the three linked Python-discovery tests. The terminal measurement selects the original `uv` compiler executable, argv and PID from the complete kernel process tree. Fourteen rustcs emitted on each arm, for 448 measured compiler PIDs across both hosts. The observer retains its four original 64-bit event words per PID. The bare clock independently brackets the full Cargo command with a blocking wait.

Before opening either host’s counters, the full v4 adjudicator reopened all 36 warm/fresh comparisons, covering the two role openings and sixteen measured arms on each host. Each covered 525 public sidecars and 657 metadata paths. It checked every nonliteral pair using the registered native type, header or reversible wire proof for its class. The v4 extension decoded inherited clauses and independently passed a separate eight-pair native fixture. [Per-visit native receipts](native.tsv) · [Frozen reader inventory](native-v4/frozen.json) · [Independent fixture](native-v4/independent-native-holdout.json)

| Host | Workflow / job | Boot | Earlier boots excluded |
| --- | --- | --- | ---: |
| 1931 | [41607449517 / 125820748850](https://github.com/astral-experiments/ohm/actions/runs/41607449517/job/125820748850) | `b3fc57e8-d455-4bdb-b6b0-1505261ff214` | 39 |
| 1937 | [41608956208 / 125825729654](https://github.com/astral-experiments/ohm/actions/runs/41608956208/job/125825729654) | `4fc08947-8636-4d96-a571-1dba457397b4` | 40, including host 1931 |

| Actions artifact | Original ZIP bytes | SHA-256 |
| --- | ---: | --- |
| [1931 early boot 13216798719](https://github.com/astral-experiments/ohm/actions/runs/41607449517/artifacts/13216798719) | 1,841 | `7de50076419e2b0c31f1f7c19a4351d77c73bf43644ef3708589361be1dc6fc5` |
| [1931 full 13219057661](https://github.com/astral-experiments/ohm/actions/runs/41607449517/artifacts/13219057661) | 404,402,894 | `874daf4f98fb41942f6ad31c76f2c779802193e3b7e60fee77cefbc37cbdabef` |
| [1937 early boot 13218350924](https://github.com/astral-experiments/ohm/actions/runs/41608956208/artifacts/13218350924) | 2,006 | `206d6e3a926c54f25ff231f4927f1256c55694e67f297ff31c35f32c17673351` |
| [1937 full 13219792341](https://github.com/astral-experiments/ohm/actions/runs/41608956208/artifacts/13219792341) | 403,350,498 | `d2e695a15d43b9d3046d9bf6e60d8a0e6b1ad246dac50bf53c382d9622cc11c5` |

## Offline replay

Run the following commands in a fresh checkout of this evidence commit. The verification used Linux and Python 3.12.13.

```sh
cd scripts/benchmark_results/uv-21134-handwritten-impl
sha256sum -c SHA256SUMS
python3 -ISB replay.py
```

The 3.56 MB archive contains 663 distinct, byte-preserved inputs (246,889,500 bytes before compression), including the full cold and measured kernel streams read by the scorer. It stores identical content only once. The packet maps each file to its original member name and content SHA. The replay authenticates both early ZIPs, the Actions records, the source and SDK identities, and the complete 36-receipt closure. It runs the original scorer to rederive every counter, clock, paired threshold, TSV and the exact two-host verdict. Four adverse checks exercise a changed counter word, the wrong rustc PID, an omitted native comparison and a reused host. [Archive member index](packet.json) · [Original scorer](../../uv-check-21134/score.py) · [Complete adjudication](replication.json)

To verify every selected byte against the full service ZIPs, pass `--originals INITIAL_DIR REPEAT_DIR`. Each directory must contain its authentic `original.zip`, `boot.zip`, `run.json`, `jobs.json` and `artifacts.json`. To independently reconstruct the native metadata proofs from the original rmeta bytes, also pass `--sdk-f F_SDK --sdk-g G_SDK` with both exact installed SDKs. That path restores the frozen worker sources and three v4 replacements in a temporary directory, uses both actual compilers, and requires the same original verdict. The compact replay checks the recorded native proofs. Full reconstruction requires the original metadata bytes and both SDKs.

## Separate local mechanism observation

On one ordinary full-process Callgrind visit per compiler, terminal `uv` used 17,025,396,126 guest instructions on F (PID 41690) and 14,681,418,121 on G (PID 41514). Separate provider traces found that 7 of 37 preregistered borrow checks skipped and 30 still ran. The seven had cost 96,609,701 instructions on F. A native failure trace found changed inputs for all 30 survivors, including moved source spans and the `Display` and `PartialEq` inventories. This local experiment has a different counter and population from the two hardware panels. The compact replay checks both full guest profiles and the recorded owner counts. [F profile](mechanism/F.callgrind.gz) · [G profile](mechanism/G.callgrind.gz) · [Owner join](mechanism/owners.json.gz) · [Source and input identities](mechanism/source-origins.json.gz)
