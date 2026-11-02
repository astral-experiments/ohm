# Trait impl directories after a real edit to uv

We held this patch after two of 16 ordinary checks exceeded our preset wall-time limit.

On the landed direct deserialization change for `PypiFile` and `PyxFile`, moving one incremental dependency from each potential impl supplier to the crate that defines the trait cut retired user instructions by 0.884% across the eight dirty rustc processes. Every crate improved in every one of the eight pairs. The median paired wall-time speedup for this change alone was 0.9993×. [uv edit](https://github.com/astral-sh/uv/pull/21041) · [Marginal run](https://github.com/astral-experiments/ohm/actions/runs/41473622846)

| Comparison after the edit | Parent median | Candidate median | Median paired parent / candidate | Pairs faster |
| --- | ---: | ---: | ---: | ---: |
| This change, eight rustcs | 8.65629 B instructions | 8.57981 B instructions | 1.008919× | 8/8 |
| This change, Cargo and descendants | 9.24610 B instructions | 9.16951 B instructions | 1.008352× | 8/8 |
| This change, ordinary Cargo check | 1.19493 s | 1.19458 s | 0.999293× | 4/8 |
| This change, independent ordinary Cargo check | 1.57450 s | 1.56301 s | 1.038413× | 11/16 |
| Full compiler stack vs. corrected Ohm −22, eight rustcs | 17.24429 B instructions | 8.57981 B instructions | 2.009865× | 8/8 |
| Full compiler stack vs. corrected Ohm −22, Cargo and descendants | 17.83407 B instructions | 9.16957 B instructions | 1.944928× | 8/8 |
| Full compiler stack vs. corrected Ohm −22, ordinary Cargo check | 2.14102 s | 1.32757 s | 1.527307× | 8/8 |
| This change, separate ordinary Cargo build after uv #20992 | 1.76292 s | 1.73244 s | 1.014791× | 7/8 |

Each ratio uses its own physically paired observations. The adjacent columns give the two separate medians. The initial ordinary check had two slow candidate visits. Pair 3 took 2.97191 s against 1.17587 s on the parent. Pair 6 took 2.43674 s against 1.21598 s. Both are included above. The build used the landed `uv cache size --output-format` change, with `cargo build --locked --offline -j8 -p uv-cli`. [Ordinary build](https://github.com/astral-experiments/ohm/actions/runs/41475005437) · [uv build edit](https://github.com/astral-sh/uv/pull/20992)

## Why we held the patch

The independent run started 32 genuine cold parent histories. Our decision, recorded before collecting these times, required all four block medians to stay below 1.05× candidate / parent, at least 15 of 16 pairs below 1.20×, and zero at or above 2×. The block medians were 0.893814, 0.964460, 0.967352 and 1.001648. Fourteen pairs stayed within the 1.20× limit. Pair 3 went from 1.37742 s to 1.70210 s and pair 5 went from 1.48244 s to 1.80470 s. Every new visit in both directions was within 1.5×. [Independent ordinary run](https://github.com/astral-experiments/ohm/actions/runs/41484215521)

Both affected visits used more child CPU time. Pair 3 also incurred 189 major faults on the candidate, while pair 5 had zero. All 32 visits recorded zero cgroup throttling time. These observations leave the cause unresolved. The wall packet retains every new clock, resource snapshot and Cargo completion message, and the earlier two slow candidate visits. This result closed the conditional second-worker cumulative comparison.

## What changed in rustc

When collecting impls of a foreign trait, rustc checked every loaded crate and recorded each supplier's directory as an incremental dependency. The lookup now fingerprints the relevant directories once for the crate that defines the trait. It traverses the existing crate roster and directory keys in order. The existing query that reads actual impls handles each positive match. Legacy positional directories contribute their supplying crate's private hash even when empty.

Across 64 saved compiler graphs, dependency reads fell from 238,667 to 793 and the number of directory fingerprint nodes fell from 2,353 to 120. The 25,677 reads of actual impl payloads were identical. Qualification included native compile and incremental tests, cross-reading metadata, migration from earlier incremental directories, and linked executable behavior. The review port is based on Rust PR #328. The timed parent `ac67101c` already includes the other compiler changes in the full stack. Exact source and schema identities are in `source.json`. [Rust #328](https://github.com/astral-experiments/ohm-rust/pull/328) · [Production compiler build and checks](https://github.com/astral-experiments/ohm/actions/runs/41459079009)

## What the cumulative comparison measures

Both arms use the same signed Ohm −22 Cargo binary and the same uv sources. The −22 Rust control includes the relocated-constant-allocation correction needed to compile the native fixture. The full stack includes the trait directory change. Each arm starts with its own cold build of the parent uv revision, then checks the real edit with `cargo check -p uv-client --locked --offline -j8`. The parent and edited revisions are `a2a02424` and `9049e07f`.

On the first worker, all eight rustc instruction ratios exceeded 2×, ranging from 2.009786× to 2.010114×. Each observation sums hardware counts for the eight rustc processes identified by their kernel exec events. The whole-Cargo count also includes Cargo and its other descendants. The ordinary Cargo measurement comes from a separate unwrapped invocation. The previously replicated 2.15× and 2.18× ordinary wall-time gains apply to a different edit, uv #22958. [Direct eight-pair run](https://github.com/astral-experiments/ohm/actions/runs/41482043357) · [Independent wall-time replication on uv #22958](https://github.com/astral-experiments/ohm/tree/300dd60e623aa5f668213a362035b79c7d09cf1a/scripts/benchmark_results/uv-22958-generated-impl-check/independent-replication)

## Replay the observations

From this directory, run the commands below with Python 3.11 or newer. The included samples are sufficient to reproduce the paired results. `series.json` and the packet manifests identify the original service archives and their SHA-256 digests.

```sh
sha256sum -c SHA256SUMS
python3 -ISB replay.py marginal
python3 -ISB replay.py build
(cd direct && python3 -ISB verify.py)
(cd ordinary-wall && python3 -ISB replay.py)
```
