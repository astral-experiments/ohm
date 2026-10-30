# Packing old native objects in Ruff parser branch builds

This measures complete storage for Rust’s incremental build state and Cargo’s target outputs when switching between the two revisions in Ruff #28335. The edit changes the layout of `ruff_python_ast::Expr` from 64 to 56 bytes in the real parser. Each installation began with empty target and shared build directories. Every visit ran `cargo +ohm build -p ruff_python_parser --locked --offline -j4 --message-format=json`. [Ruff edit](https://github.com/astral-sh/ruff/pull/28335) · [Hosted study](https://github.com/astral-experiments/ohm/actions/runs/41049570613)

| Visit | Default | Current branch-cache draft | Branch cache with packed objects |
| --- | ---: | ---: | ---: |
| First visit to the feature | 271.93 MiB | 321.85 MiB | 313.36 MiB |
| Return to the parent | 286.83 MiB | 277.88 MiB | 260.87 MiB |
| Return to the feature | 256.64 MiB | 279.23 MiB | 262.24 MiB |
| First dirty edit on the feature | 271.50 MiB | 317.46 MiB | 308.94 MiB |

The table gives median allocated blocks after the command exited, including directories and counting each physical inode once across both roots. A separate sparse-file and hardlink calibration checked the accounting. The study ran on the runner’s own filesystem. It does not establish peak allocation during a command.

After returning to the feature, packing saved 17.03 MiB relative to the current opt-in draft. The pointwise 96.14% paired interval was 16.97–17.06 MiB. The median excess over the default fell from 22.59 MiB to 5.60 MiB. After the first feature visit the excess was still 41.43 MiB. Whole-CLI footprints require a separate measurement.

| Whole Cargo command | Default | Current branch-cache draft | Branch cache with packed objects |
| --- | ---: | ---: | ---: |
| First visit to the feature | 3.229 s | 3.379 s | 3.406 s |
| Return to the parent | 3.245 s | 0.976 s | 0.992 s |
| Return to the feature | 3.285 s | 1.215 s | 1.253 s |
| First dirty edit on the feature | 3.219 s | 3.432 s | 3.450 s |

The median within-triplet speedups versus the default were 3.27× (3.19–3.28) and 2.62× (2.60–2.66) on the two returns. Packing made those returns 2.0% and 2.8% slower than the current branch-cache draft. These are 12 counterbalanced triplets measured after a separate two-triplet pilot. The three-way design used signed release Cargo and Wild in the same paths. Its independently rebuilt 63-file compiler runtimes differed only in the rustc driver. The candidate with the flag omitted supplied the default arm. The parent with the flag enabled supplied the current-draft arm. The candidate with the flag enabled supplied the packed-object arm.

Empty builds provided separate native references for each arm and checkout. Every positive visit reproduced its reference reader executable, native archive object payloads and matching expression layout. A contrary typed layout failed, the invalid parser edit failed, and the repaired edit succeeded. In all 288 successful confirmation visits, at least one archive differed from its clean reference in `lib.rmeta`. Native object bytes and normalized link indexes agreed in every comparison. In a native archive control the caller changed from 17 to 29, a truncated library failed and the repaired executable matched clean.

## Compiler instructions on the two branch returns

Two additional triplets ran in opposite arm orders. Each return invoked exactly two compilers, for `ruff_python_ast` and `ruff_python_parser`, and zero Wild linkers. The table sums complete Callgrind `Ir` counts for those two rustc processes. It excludes Cargo and the independently executed native verifier. The time measurements above come from separate runs.

| Return and run order | Default | Current branch-cache draft | Packed | Default / packed |
| --- | ---: | ---: | ---: | ---: |
| Parent, forward | 67.657 B | 13.433 B | 13.929 B | 4.857× |
| Parent, reverse | 67.637 B | 13.431 B | 13.936 B | 4.853× |
| Feature, forward | 67.925 B | 16.922 B | 17.657 B | 3.847× |
| Feature, reverse | 67.959 B | 16.922 B | 17.662 B | 3.848× |

Packing added 3.69–3.77% to compiler instructions on the return to the parent and 4.35–4.38% on the return to the feature, relative to keeping the old objects uncompressed. The raw verifier sums the exclusive instruction counts in each profile, validates the terminal counter, process identity and captured compiler arguments, and reopens the observed native outputs against independently clean builds.

## Replay

With Python 3.11 or newer, run the commands in this directory.

```sh
sha256sum -c SHA256SUMS
python3 -IB verify.py
python3 -IB verify_instructions.py
```

The compressed observations include every ordinary elapsed time and disk measurement for the two pilot and twelve confirmation triplets, native compiler and linker counts, reference identities and result hashes. To repeat the full check against the hosted archive, download the `packed-object-ruff-ordinary` artifact while it is available and supply the original ZIP. Its SHA-256 is `6b57edb09de2a77f6dbec1fe4bb0b80c9aac845bbc7a001b3019f62e76570218`.

```sh
python3 -IB verify.py --raw /path/to/packed-object-ruff-ordinary.zip
```

To repeat the counter verification, also download `packed-object-ruff-instructions` from the same run. Its SHA-256 is `e8b5cf57d5879b7c688206d1a16e89b471ae5f6dd5d11b375cd6d1473bb92a81`.

```sh
python3 -IB verify_instructions.py --raw /path/to/packed-object-ruff-ordinary.zip /path/to/packed-object-ruff-instructions.zip
```
