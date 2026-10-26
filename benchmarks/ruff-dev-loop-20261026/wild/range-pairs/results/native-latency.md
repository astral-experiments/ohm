# Native workspace test-build latency

Each run timed the real `cargo +ohm test --no-run` command through process exit on four pinned CPUs. The complete two-file historical edit rebuilt the formatter integration test, and each run matched all 619 Cargo artifacts and 102 native executable digests. Source resets and output verification ran outside the timed interval. The two separately ordered 12-block schedules used the same warm target.

| Schedule | Baseline | Baseline median (s) | Candidate median (s) | Paired reduction (95% CI) | Favorable pairs | Exact two-sided p |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Primary | Wild #42 | 1.852 | 1.845 | 4.98% (-5.13% to 14.97%) | 7/12 | 0.2963 |
| Primary | Ohm #185 | 1.842 | 1.845 | -2.50% (-10.45% to 4.84%) | 5/12 | 0.5278 |
| Replication | Wild #42 | 1.924 | 1.789 | 5.86% (0.69% to 10.74%) | 8/12 | 0.0741 |
| Replication | Ohm #185 | 2.026 | 1.789 | 11.44% (4.94% to 17.65%) | 9/12 | 0.0556 |

The registered test required both confidence intervals to favor the candidate, an exact two-sided probability at most 0.05 on both schedules, and an improvement in both edit directions on each. [Registered gate](../native-timing-plan.json)

- Against Wild #42, the native latency comparison was inconclusive under the registered gate.
- Against Ohm #185, the native latency comparison was inconclusive under the registered gate.

The raw durations include child CPU seconds as a diagnostic. [Primary durations](test-native.csv), [primary intervals and edit directions](test-native-summary.json), [replication durations](test-native-replication.csv), [replication intervals and edit directions](test-native-replication-summary.json)
