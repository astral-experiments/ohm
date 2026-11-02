# The first Cargo check after the uv wheel edits

The cumulative rustc candidate was `ac67101cb973e35ce8ff044cc8014c2c76bab69e`. The shipped Ohm −22 compiler passed the warm/cold native checks on this edit sequence and served as the control. Both Cargo processes came from the signed release. The effects below apply to the full compiler change set.

The control was signed Ohm −22. Both arms used signed −22 Cargo and the ordinary `cargo check -p uv-client --locked --offline -j8` command. Each of eight pairs started from independent cold parent builds before the three real edits. [uv #22536](https://github.com/astral-sh/uv/pull/22536) · [Hosted run](https://github.com/astral-experiments/ohm/actions/runs/41531636175)

| Edit | Control, s | Candidate, s | Paired speedup | Pairs >2× | All-process instruction cut | Six rustcs, summed cut |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Wheel selection | 1.943 | 1.029 | 1.787× | 1/8 | 50.64% | 53.23% |
| Documentation | 1.110 | 1.016 | 1.040× | 0/8 | 4.07% | 4.51% |
| Public API rename | 1.840 | 1.051 | 1.666× | 0/8 | 45.26% | 47.81% |
| Two code edits | 3.783 | 2.080 | 1.744× | 0/8 | 48.07% | 50.65% |
| Full edit sequence | 4.893 | 3.097 | 1.496× | 0/8 | 39.01% | 41.52% |

Each time column is a median of eight ordinary wall measurements. The speedup and instruction cuts are medians of within-pair ratios. The two-code-edit row sums the feature and rename times within each arm.

## Instructions retired by each compiler

| rustc | Wheel selection cut | Pairs >20% | API rename cut | Pairs >20% |
| --- | ---: | ---: | ---: | ---: |
| `uv_cache` | 48.37% | 8/8 | 40.81% | 8/8 |
| `uv_client` | 64.76% | 8/8 | 59.36% | 8/8 |
| `uv_configuration` | 47.77% | 8/8 | 40.12% | 8/8 |
| `uv_distribution_types` | 41.36% | 8/8 | 36.23% | 8/8 |
| `uv_metadata` | 38.50% | 8/8 | 43.36% | 8/8 |
| `uv_torch` | 43.44% | 8/8 | 38.37% | 8/8 |

12 of the 12 preregistered compiler/edit comparisons cleared 20% in every pair and in both four-pair halves. The adjusted one-sided sign-test probability for an 8/8 result is 12/256 across this family.

The strict 2× wall threshold was exceeded in 8/8 pairs on 0 of the three preregistered wall endpoints. None qualified for the second wall-time cohort.

The original contains 16 distinct cold kernel traces. The standalone reader reran the native product checks and recovered the statistics from its authenticated archive, SHA-256 `2c7feb8d80794c0c5262cb1fcebebb075b72d308206b94ea499c2bbf0708ffa6`. [Original reader and protocol](https://github.com/astral-experiments/ohm/tree/ca8b83712b881b45cbb8e8b0513d0811971e4a98/scripts/uv-check-22536).

The hosted job completed the acquisition and independent scoring, then failed to import a sibling module in its final native verifier. The isolated failure reproduced on the original archive. With the reviewed module directory on the import path, the unchanged verifier produced the same verdict as the original standalone reader. The independent scorer reproduced its hosted output byte for byte. GitHub records the original job as failed.


## Reproduction

From the root of this checkout, run

```sh
python3 -ISB scripts/benchmark_results/uv-22536-wheel-ranking-check/replay.py > /tmp/uv-22536-replay.json
```

The replay ran with Python 3.12 and the zstd CLI. It decompresses the exact GitHub artifact, checks both ZIP digests, and runs the original reader on every member. That reader validates the native compiler and Cargo records and recomputes all paired statistics. The output includes all eight raw values for each comparison.

A separate reduction checked 48 bare Cargo waits and 288 per-process instruction records. Twelve of twelve compiler/edit series cleared the prespecified threshold. Each series spans eight pairs on the same hosted worker. [Independent reduction](independent-raw-endpoints.json) · [Hashes and service status](verification.json) · [Postprocessing rule recorded before opening the numbers](blind-postprocess-rule.json)

Three earlier workers stopped during source intake or native verification. The eight reported pairs all come from the fourth worker. [First worker](https://github.com/astral-experiments/ohm/actions/runs/41513162578) · [Second worker](https://github.com/astral-experiments/ohm/actions/runs/41520398434) · [Third worker](https://github.com/astral-experiments/ohm/actions/runs/41523955754)
