# Ordinary Ruff builds with tracked generator-specific Rust settings

At the same generator opt-level 1, disabling generic sharing reduced instructions on the first unchanged `ty_project` check by **1.285× and 1.282×** on two native Linux workers. The corresponding `ruff_unicode_names2` linked-library builds improved **1.722× and 1.726×**. The flag saved about one third of a MiB in a fresh target, but switching a populated one retained **387.85 to 388.20 MiB** more across target and shared storage. Every mixed-state disk gate failed. [Registered plan](../PLAN.md) · [Native run](https://github.com/astral-experiments/ohm/actions/runs/41157269898)

All four arms used ordinary Rust and Cargo entry points with no compiler wrapper. A was default opt 0 for the host generator, B set only that package to opt 1, Q added one compiler flag to B, and C set only that package to opt 2. Worker 01 ran ABQC and the reversed real edit, worker 02 CQBA and the forward edit. The private Cargo config was common except for those explicit package choices. This is the complete Q config:

```toml
[unstable]
profile-rustflags = true

[profile.dev.package.ruff_unicode_names2_generator]
opt-level = 1
rustflags = ["-Zshare-generics=no"]
```

We pinned Ruff `93526150` and its 498 registry archives, release-style Cargo `761ea115` (ELF `035e6810`), signed `-21` rustc `c79998a5` and signed Wild. Both workers exercised the real `ty_project` edit from `32c5cd5d` and the generator edit from `bfedc614b7`. Each paid command used untraced, inherited, whole-process hardware user instructions. All 56 direct, fork, descendant exec and thread calibration calls passed. The two workers provide descriptive comparisons.

```sh
cargo +ohm check -p ty_project --tests --locked --offline -j8 --message-format=json
cargo +ohm build -p ruff_unicode_names2 --lib --locked --offline -j4 --message-format=json
```

| ty_project check | Billions, A / B / Q / C on 01 | Billions, A / B / Q / C on 02 | Same opt-level B/Q | Combined A/Q |
| --- | --- | --- | --- | --- |
| Empty | 493.748 / 492.542 / 491.179 / 492.452 | 493.668 / 492.538 / 491.158 / 492.522 | 1.003 / 1.003 | 1.005 / 1.005 |
| Unchanged before edit | 16.581 / 9.094 / 6.962 / 6.860 | 16.578 / 9.103 / 6.952 / 6.861 | 1.306 / 1.309 | 2.382 / 2.385 |
| Real edit | 19.444 / 11.972 / 9.820 / 9.733 | 19.474 / 11.973 / 9.826 / 9.724 | 1.219 / 1.218 | 1.980 / 1.982 |
| First unchanged | 17.181 / 9.705 / 7.550 / 7.449 | 17.186 / 9.690 / 7.559 / 7.449 | 1.285 / 1.282 | 2.276 / 2.274 |
| Edit plus first unchanged | 36.625 / 21.678 / 17.370 / 17.182 | 36.661 / 21.662 / 17.385 / 17.173 | 1.248 / 1.246 | 2.109 / 2.109 |

| Linked library build | Billions, A / B / Q / C on 01 | Billions, A / B / Q / C on 02 | Same opt-level B/Q | Combined A/Q |
| --- | --- | --- | --- | --- |
| Empty | 24.981 / 23.849 / 22.473 / 23.745 | 24.938 / 23.794 / 22.492 / 23.685 | 1.061 / 1.058 | 1.112 / 1.109 |
| Unchanged before edit | 12.629 / 5.150 / 2.990 / 2.885 | 12.618 / 5.127 / 2.988 / 2.885 | 1.722 / 1.716 | 4.223 / 4.223 |
| Real generator edit | 13.215 / 8.017 / 6.239 / 7.660 | 13.216 / 8.020 / 6.237 / 7.667 | 1.285 / 1.286 | 2.118 / 2.119 |
| First unchanged | 12.616 / 5.137 / 2.984 / 2.894 | 12.620 / 5.137 / 2.976 / 2.885 | 1.722 / 1.726 | 4.229 / 4.241 |
| Edit plus first unchanged | 25.831 / 13.154 / 9.223 / 10.554 | 25.836 / 13.157 / 9.212 / 10.552 | 1.426 / 1.428 | 2.801 / 2.804 |

The simpler single-package opt 2 gave 2.306× / 2.307× on the unchanged check and 4.360× / 4.374× on the unchanged library build against default. Q used fewer instructions than C on the real generator edit and on the empty library build. The A/Q ratios combine a profile change and a sharing change. B/Q isolates the additional flag at level 1. [Complete paired records](verified.json)

Each cold check ran 304 full rustcs and 48 actual Wild links, with 338 Cargo units and 303 emitted Cargo artifacts. All 254 expected shared-stage compiler invocations returned, including all 31 Ruff workspace compilations. All 304 cold rustcs entered the physical signed compiler without a preceding executable on that PID. The B/Q unit graphs differ at one field on one unit, which adds `rustflags = ["-Zshare-generics=no"]`. Comparing the real compiler's entire `-C` and `-Z` sequences leaves exactly that one added flag after accounting for Cargo artifact identifiers and incremental output directories. The ordinary primary repeat ran three full compilers (`build_script_build`, `ron` and `unicode_names2`), one Wild link and the generator. The linked secondary returned to its original one real compiler and one Wild on repeat, with 17 compilers and one Wild on its empty control. At natural opt 2, Cargo also omitted its three level-0/1 incremental codegen flags on the generator. [Physical verifier](reopen.py)

All arms reproduced the three complete generated source files, identical native reader outputs for four code points, original or edited logical inventories, and expected debug assertions and overflow behavior. The default and opt-1 generator ELFs matched their independently archived originals byte-for-byte. The warm and independent-empty invalid source gave the same E0308 and its repaired source checked cleanly. B and Q separately passed 36 unscored native-provider visits in total. Real Wild and the generator's loader observed a held higher-priority provider returning 83 and then 47 under the same inode, byte length and mtime. Malformed replacement failed and removal restored 0 as on an empty target. Every migrated generator matched the fresh complete executable for its active mode.

| First genuine profile transition | Switch instructions | Switch full rustcs / Wild | Pure → settled allocated MiB | Increase MiB |
| --- | ---: | --- | ---: | ---: |
| B → Q, worker 01 | 106.629B | 16 / 1 | 794.965 → 1,182.816 | 387.852 |
| Q → B, worker 02 | 108.047B | 16 / 1 | 794.598 → 1,182.801 | 388.203 |
| A → Q, worker 01 | 106.646B | 16 / 1 | 795.992 → 1,183.848 | 387.855 |
| A → Q, worker 02 | 106.625B | 16 / 1 | 795.992 → 1,183.844 | 387.852 |

Returning to the earlier profile needed three rustcs and one Wild. Mixed allocation persisted within 0.016 MiB. The Q/B fresh check targets differed by −0.328 / −0.371 MiB, and Q used 0.277% / 0.280% fewer cold instructions. The disk budget capped a populated target's increase at 10% and 80 MiB. The B→Q and Q→B increases comprise 356.06–356.07 MiB in `target/debug/incremental`, 25.23–25.25 MiB in inodes with cross-directory aliases (counted once), and 6.56–6.88 MiB in `target/debug/build`. Every paid total is independently tied to its original allocated-block ledger and GNU du.

The native jobs also hashed every `ohm-check-dep-graph.bin` and `query-cache.bin` in the private incremental target outside the counters. Newly allocated same-crate graph/query files after the first transitions accounted for about 243.45 MiB / 82.84–82.90 MiB and had distinct whole-file hashes from their corresponding original caches. Each new `ty_python_semantic` dep graph and query cache also differed from its previous file. The packet retains per-file hashes and stats. Rehashing the full cache payloads would require the original hosts. The pre-switch content reader ran after the unscored physical repeat. On each baseline three paths belonging to `build_script_build` and `unicode_names2` changed generation since the preceding paid ledger. These are explicitly listed as separate snapshots. Both `ty_python_semantic` files and the other 57 unaffected entries match the paid baseline, and all 89 post-switch rows match their adjacent paid ledger. For the earlier twelve-host package-only study, all 48 old/new semantic-file comparisons already differed in complete length. [Original length records](prior-semantic-file-lengths.json) · [Earlier study](https://github.com/astral-experiments/ohm/tree/e2dffc67a5a3eeab53b8e1fcded93f7896dc325c/scripts/strict-one-package/result)

The two original GitHub ZIPs and their artifact metadata are stored alongside the verifier. From this directory:

```sh
python3 -IB reopen.py . | cmp - verified.json
python3 -IB extract_elf.py unwrapped-profile-01.zip unwrapped-profile-01.json 01 Q /tmp/ohm-qualified-q-elf
# Optional, with the earlier twelve-host packet
python3 -IB prior_lengths.py /path/to/strict-one-package/result | cmp - prior-semantic-file-lengths.json
```
