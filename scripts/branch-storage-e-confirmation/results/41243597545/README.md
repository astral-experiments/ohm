# Ruff branch-return builds on 12 Linux machines

With branch retention enabled, rustc used 6.16× fewer retired instructions than the default to return to A and then B in a 375-unit Ruff CLI build. The existing implementation in #274 was faster on those two returns. This change traded 13.72% more instructions than #274 for at least 488 MiB less disk use at the first switch on every worker. [Compiler change](https://github.com/astral-experiments/ohm-rust/commit/393b4b05a4bfa3f531a36023846f86236a6b71a9) · [Parent PR](https://github.com/astral-experiments/ohm-rust/pull/274)

Each worker ran the same tests with the ordinary default (Foff), #274 enabled (Fon), and the revised cache enabled (Eon). The order of these three configurations was counterbalanced. The independent working histories included a direct switch and a switch after a real Ruff parser edit on the original branch. Sizes are allocated blocks across both the build and target directories. Shared hardlinks count once. [Plan](../../PLAN.md) · [Final compiler enrollment](../../SOURCE-ADDENDUM.md) · [Original run and artifacts](https://github.com/astral-experiments/ohm/actions/runs/41243597545)

| Paired result | Median | Interval from worker ranks 2 and 11 | All 12 workers |
| --- | ---: | ---: | ---: |
| Default / revised instructions, return to A | 6.44360× | 6.44225–6.44449× | 6.44188–6.44583× |
| Default / revised instructions, return to B | 5.89988× | 5.89902–5.90084× | 5.89832–5.90096× |
| Default / revised instructions, both returns | 6.15953× | 6.15865–6.15988× | 6.15837–6.16045× |
| Largest first-switch excess over default | 6.443 MiB | 6.270–6.598 MiB | 6.148–6.660 MiB |
| Smallest first-switch saving over #274 | 488.555 MiB | 488.480–488.680 MiB | 488.473–488.738 MiB |

All five predeclared thresholds held on every worker. The intervals have simultaneous coverage of at least 96.826% under the registered sampling assumptions. The 396 hardware counters were fully scheduled and needed no scaling. The complete run also included 396 ordinary commands, 108 independent empty builds, parser and f-string verdicts, malformed source and repair, and 36 native-library replacement panels. Both readers checked each edited Ruff executable against an independently empty build before opening the counters. [Full results and controls](result.json) · [Independent counts and allocated bytes for every visit](counts-and-bytes.json)

The improvement from an empty checkout through both return builds was 1.33× versus default. The existing #274 used 241.48 billion instructions for the two returns versus 274.61 billion here. The revised cache used 1.92% more than #274 for a cold build, 2.65% more for the first switch and 8.52% more on the same-branch edit. The earlier pilot target of at most 10% added return work was missed on all 12 machines. The other pilot margins held.

After a direct first switch the revised cache was about 27 MiB smaller than default. After the switch following a same-branch edit, it was about 6 MiB larger. After fixing invalid source it retained about 288 MiB more than default and 173 MiB less than #274. The workers used shared filesystems, so these measurements establish allocation at the end of each command. Peak allocation during compilation was unavailable. [Both allocation histories, absolute counts and comparisons](phase-medians.txt)

The archived outputs are from the exact corrected compiler. The prior prototype could use an older object when a raw and a packed representation of the same name coexisted. The candidate rejects either ordering of that collision and recompiles. This check does not authenticate a lone raw object from a corrupt cache. [Source regression and original native runs](../../SOURCE-ADDENDUM.md)

Run the receiver from the measurement commit `b1f863353a63c91bebf5d2bc2ca68a4aca93f6bb` with run ID `41243597545`. It requires GNU x86-64, the original compiler archives and enough space for 4.36 GB of original worker ZIPs. The result file SHA-256 is `2ed5fd79d13c4b1ce4c46ac52ca888bab1e956d3f187f8a53b2fe523f7494da2`. [Receiver commands](../../README.md#reopen-a-finished-confirmation)
