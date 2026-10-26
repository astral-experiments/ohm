# Whole-command instruction counts after historical Ruff edits

Each comparison uses twelve matched blocks of the full default workspace command. The three linkers are proposed ThinLTO Wild (`control`), the existing Wild #42 changes (`middle`) and those changes with paired DWARF range endpoints (`candidate`). The table reports the geometric reduction for the candidate versus each baseline.

| Historical edit | Baseline | Median baseline instructions | Median candidate instructions | Whole-command reduction (95% CI) | Favorable pairs | Exact two-sided p | Wild reduction |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Full test build, formatter fixture | Wild #42 | 5.8126B | 5.7858B | 0.471% (0.370% to 0.564%) | 12/12 | 0.00926 | 2.447% |
| Full test build, formatter fixture | Ohm #185 | 5.9276B | 5.7858B | 2.397% (2.295% to 2.491%) | 12/12 | 0.00926 | 11.967% |
| Independent test-build replication | Wild #42 | 5.8145B | 5.7836B | 0.505% (0.424% to 0.585%) | 12/12 | 0.00926 | 2.448% |
| Independent test-build replication | Ohm #185 | 5.9287B | 5.7836B | 2.478% (2.407% to 2.549%) | 12/12 | 0.00926 | 11.960% |

The complete historical patch and edit direction were identical across the three arms in each block. The table uses the recorded Cargo, rustc, Clang and Wild guest instructions after verifying the whole native ELF set and full process roster. The bootstrap interval resamples within edit directions. The exact test conditions on the position of the third arm and enumerates the 216 assignments permitted by the six balanced arm orders. All measurements used the same two instruction-counting engines across arms. [Frozen plans, native oracles and reproduction](../README.md)

## Raw observations

- Full test build, formatter fixture. [Command counts](test.csv), [per-process records](test-processes.jsonl), [intervals and direction splits](test-summary.json)
- Independent test-build replication. [Command counts](test-replication.csv), [per-process records](test-replication-processes.jsonl), [intervals and direction splits](test-replication-summary.json)

The second test-build measurement was added before the primary test cohort finished. It reused the independent schedule already frozen for an elapsed-time replication, the same warm target and the same native checks. Its sample is separate from the primary twelve blocks.

The full formatter-build cohort is still in progress.

Both separately registered native elapsed-time cohorts are reported alongside their raw durations. [Native command timing](native-latency.md)
