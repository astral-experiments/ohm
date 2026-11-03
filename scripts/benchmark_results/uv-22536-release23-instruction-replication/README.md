# Ordinary Cargo checks for the uv wheel-ranking changes on Ohm −23

On the public type rename, **`uv_metadata` used 21.971% and 21.973% fewer instructions** on independent workers. All eight pairs and both four-pair medians cleared 20% on each. This was the only one of the twelve named compiler comparisons to repeat above the threshold. Median retired instructions fell from 247.19M to 192.87M on both.

The control was the signed Ohm 1.99.0−23 compiler `d57fd151`. The candidate was the matched release-optimized `60bd529e` compiler. This comparison measures the cumulative Rust changes. Each arm ran the same signed −23 Cargo and the ordinary command `cargo check -p uv-client --locked --offline -j8`. The four consecutive uv revisions included the original parent, the wheel variant ranking implementation, a documentation/review edit, and the public type rename. [uv #22536](https://github.com/astral-sh/uv/pull/22536) · [Compiler and Cargo inventories](https://github.com/astral-experiments/ohm/blob/5207caa0f51f9458b5b29f55aba5b301bf4e7b48/scripts/uv-check-22536/release23-inputs.json)

## Ordinary wall time

Each time is a median of eight unwrapped Cargo invocations. Factors are medians of the paired control/full ratios. The two sequence rows sum each matched pair's actual commands.

| Edit | Worker 1, signed → full (s) | Paired factor | Worker 2, signed → full (s) | Paired factor | Pairs over 2×, workers 1 / 2 | Six rustcs, instruction cut, workers 1 / 2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Wheel ranking | 0.9136 → 0.8752 | 1.0459× | 0.9179 → 0.8691 | 1.0526× | 0/8, 0/8 | 4.75% / 4.75% |
| Documentation | 0.8928 → 0.8484 | 1.0553× | 0.8901 → 0.8458 | 1.0524× | 0/8, 0/8 | 4.99% / 4.99% |
| Public type rename | 0.9436 → 0.8951 | 1.0539× | 0.9333 → 0.8924 | 1.0494× | 0/8, 0/8 | 5.12% / 5.12% |
| Both code edits | 1.8550 → 1.7761 | 1.0502× | 1.8459 → 1.7633 | 1.0464× | 0/8, 0/8 | 4.93% / 4.94% |
| All three checks | 2.7514 → 2.6228 | 1.0526× | 2.7435 → 2.6048 | 1.0506× | 0/8, 0/8 | 4.95% / 4.95% |

## Retired instructions in the twelve preselected comparisons

Each percentage is one minus the reciprocal of the median paired instruction factor. Counts show the number of pairs with a strict reduction over 20%.

| Compiler | Wheel ranking, workers 1 / 2 | Pairs over 20% | Type rename, workers 1 / 2 | Pairs over 20% |
| --- | ---: | ---: | ---: | ---: |
| `uv_cache` | 12.34% / 12.34% | 0/8, 0/8 | 11.68% / 11.68% | 0/8, 0/8 |
| `uv_client` | 6.40% / 6.40% | 0/8, 0/8 | 6.02% / 6.02% | 0/8, 0/8 |
| `uv_configuration` | 5.09% / 5.10% | 0/8, 0/8 | 4.68% / 4.68% | 0/8, 0/8 |
| `uv_distribution_types` | 0.74% / 0.74% | 0/8, 0/8 | 0.33% / 0.33% | 0/8, 0/8 |
| `uv_metadata` | 4.17% / 4.17% | 0/8, 0/8 | 21.97% / 21.97% | 8/8, 8/8 |
| `uv_torch` | 9.14% / 9.14% | 0/8, 0/8 | 8.54% / 8.54% | 0/8, 0/8 |

Across both code edits, aggregate instructions in the six rustcs decreased by 4.93% and 4.94%. Whole-Cargo instructions decreased by 4.47% and 4.48%. The named-process counters include the compiler's threads and exclude child processes. Independent visits measured whole-command instructions and ordinary wall time.

## Native checks and replay

Each worker chose the actual signed R baseline after checking the real A/B/C/D histories, the corresponding independent cold outputs and unchanged visits. The reader checked 39 workspace metadata products, 423 public sidecars, the 42 native outputs of the six dirty compilers, the two public type names, and the upstream wheel-ranking tests. In the separate five-visit CTFE fixture the signed compiler gave different warm and cold B public hashes. The full compiler passed that fixture. Both compilers passed the registered semantic checks on these actual uv changes.

Each worker used sixteen independently prepared cold A histories, two balanced four-pair blocks, and separate native, wall, whole-command PMU and per-rustc PMU visits. The second used a new hardware boot and service runner. The one conditional repeat was fixed before the first result and retained the same arm order. `two-host.json` contains every original integer observation and names each supplementary fixed-input check that admitted a known metadata encoding difference. An earlier job stopped during source admission before calibration. [Original study](https://github.com/astral-experiments/ohm/actions/runs/41581631940) · [Independent repeat](https://github.com/astral-experiments/ohm/actions/runs/41584047291) · [Unscored startup](https://github.com/astral-experiments/ohm/actions/runs/41579999965)

From this directory, run the following with Python 3.12+ and Zstandard. It reconstructs both byte-identical GitHub service archives, verifies their native checks using the worker's original reader, reopens 576 rustc counts and 96 each of the independent wall and whole-Cargo observations, and recomputes the full table. It runs offline.

```sh
python3 -ISB replay.py
```
