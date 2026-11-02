# Which part of the compiler stack sped up uv #22958?

The stack through [Ohm Rust #328](https://github.com/astral-experiments/ohm-rust/pull/328) reduced the two rustc processes from 8.713B to 3.367B instructions. Adding [#336](https://github.com/astral-experiments/ohm-rust/pull/336) reduced instructions by a further 0.019% and made the command faster in four of eight pairs. The comparison measures #336 individually. Several earlier compiler changes separate the control from the stack through #328.

All three compilers used the signed Ohm −22 Cargo. The control used −22 rustc plus the literal-metadata correction in #318. Each measurement was the first ordinary `cargo check -p uv-client --locked --offline -j8` after applying the eight-file uv edit. The eight counterbalanced trios started from 24 independently built histories. The wall, per-rustc instructions and whole-command instructions came from separate restores. [uv edit](https://github.com/astral-sh/uv/pull/22958) · [Worker](https://github.com/astral-experiments/ohm/actions/runs/41507227765)

| Metric, median of eight visits | Corrected −22 | Stack through #328 | Add #336 |
| --- | ---: | ---: | ---: |
| Ordinary Cargo wall | 1.692 s | 0.806 s | 0.799 s |
| Terminal `uv_client` rustc instructions | 6.431B | 2.08648B | 2.08639B |
| `uv_configuration` rustc instructions | 2.283B | 1.28052B | 1.27997B |
| Both rustcs, summed | 8.713B | 3.36701B | 3.36638B |
| Whole command, including descendants | 9.562B | 4.21580B | 4.21515B |

| Comparison | Median paired wall speedup | Pairs faster | Pairs above 2× | Paired reduction in summed rustc instructions |
| --- | ---: | ---: | ---: | ---: |
| Corrected −22 → stack through #328 | 2.101× | 8/8 | 7/8 | 61.358% |
| Corrected −22 → full stack | 2.141× | 8/8 | 6/8 | 61.365% |
| Stack through #328 → add #336 | 0.999× | 4/8 | 0/8 | 0.019% |

The threshold registered before this worker required all eight paired wall ratios and both half medians to exceed two. None of the three comparisons cleared it. The two earlier workers each cleared it for the full stack, with paired medians of 2.151× and 2.181×. Across all three workers, the full stack won 24 of 24 pairs and exceeded 2× in 22. Its slowest speedup was 1.745×. [Earlier workers](../independent-replication) · [All three workers](across-workers.json) · [Registered comparisons](packet/component-plan.json)

The packet preserves 594 original members, all 24 ordinary Cargo completions, all 57 selected kernel traces and a SHA-256 index covering all 5,382 members of the service archive. The original, preregistered reader passed. From this directory, replay the counters and clocks with

```sh
python3 -ISB packet/component_evidence.py replay
```

Passing the downloaded service ZIP as a final argument also verifies every original member. The release lock records all three source revisions and SDK identities. [Source and SDK lock](packet/release-lock.json) · [Original artifact identity](packet/origin.json) · [All eight paired measurements](packet/verified.json)
