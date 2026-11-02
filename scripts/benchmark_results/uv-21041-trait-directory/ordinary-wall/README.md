# Independent ordinary Cargo wall check after uv #21041

A production Linux worker compared `ac67101c` with its direct rustc child `e4edbdd9` using the same signed Ohm −22 Cargo. Every arm built an independent clean A before timing its first ordinary `cargo check -p uv-client --locked --offline -j8` at the landed B edit. Each clock used an unwrapped blocking wait. The 32 resource snapshots surrounded those clocks. The separate restored kernel traces supply the eight actual rustc invocations and their exit statuses per visit. [uv edit](https://github.com/astral-sh/uv/pull/21041)

The prospective guard did not pass. It requires each four-pair median candidate/parent ratio to be below 1.05, at least 15 of 16 ratios below 1.20, and zero ratios at or above 2. The new paired median candidate/parent was 0.963008. The four block medians were 0.893814, 0.964460, 0.967352, 1.001648.

| Pair | Parent seconds | Candidate seconds | Candidate / parent |
| ---: | ---: | ---: | ---: |
| 1 | 2.113419544 | 1.923884902 | 0.910318 |
| 2 | 1.727115355 | 1.515214200 | 0.877309 |
| 3 | 1.377420231 | 1.702102637 | 1.235718 |
| 4 | 2.014573510 | 1.722832930 | 0.855185 |
| 5 | 1.482444878 | 1.804697931 | 1.217379 |
| 6 | 1.413909776 | 1.342606636 | 0.949570 |
| 7 | 1.413710367 | 1.360925135 | 0.962662 |
| 8 | 1.557762753 | 1.505199734 | 0.966257 |
| 9 | 1.429341252 | 1.410994936 | 0.987164 |
| 10 | 1.599423044 | 1.436428333 | 0.898092 |
| 11 | 1.617005564 | 1.686215671 | 1.042801 |
| 12 | 1.643468159 | 1.557249900 | 0.947539 |
| 13 | 1.802732544 | 1.574876941 | 0.873605 |
| 14 | 1.390010046 | 1.339072768 | 0.963355 |
| 15 | 1.591228153 | 1.726614105 | 1.085083 |
| 16 | 1.508514652 | 1.568767273 | 1.039942 |

The earlier eight-pair worker had two candidate slowdowns of at least 2×. Pair 3 took 1.175872273 s on the parent and 2.971908427 s on the child. Pair 6 took 1.215984787 s and 2.436735666 s. All eight original pairs and Cargo completion messages remain in the packet. Resource snapshots were introduced on the subsequent 16-pair run. [Earlier eight-pair workflow](https://github.com/astral-experiments/ohm/actions/runs/41473622846)

`all-32-wall-resources.csv` includes every elapsed observation, absolute monotonic start/end, CPU time, context switches, major/minor faults, block I/O, visible cgroup throttle counters and host pressure. The raw pair of Linux snapshots is preserved for each visit. A blank cell denotes an unavailable kernel source. Host and cgroup totals include overlapping system activity. They do not identify the wait reason of an individual rustc.

Run `python3 -ISB replay.py` from any directory. To compare all retained original bytes against the two authenticated original service archives, supply `--original current.zip --prior-original earlier.zip`. The compact reader independently verifies the blocking clocks, kernel roster, source edit, raw Linux counters, all threshold boundaries and every row of the wall table.

The current original is artifact `13167420281`, SHA-256 `fcf0c3028f9e12f2b0667c5b9be9ebdc870ce94c130c3430000657ba29c55e54`. The full original replay independently admitted 32 unique A checkpoints, 256 actual rustc images and 284 unique native workspace metadata blobs. [Current physical workflow](https://github.com/astral-experiments/ohm/actions/runs/41484215521)
