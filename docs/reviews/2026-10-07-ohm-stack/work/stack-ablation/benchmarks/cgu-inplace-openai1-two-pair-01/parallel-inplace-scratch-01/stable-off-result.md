# Stable CGU merging ablation

**Recommendation: retain provisionally.** Turning off stable CGU merging slowed the Codex library builds after Edits 1 and 2 in both arm orders. The two-pair median increases were 1.474 and 1.655 seconds. This is enough to justify retaining the roughly 34-line policy for that workflow, but does not establish a general win.

The cold Ruff and uv builds favored removal: their medians fell by 4.897 and 1.984 seconds, with both orders faster. Codex's cold result was mixed by order. The report should retain these costs alongside the edited-build benefit.

This compares one accepted optimized compiler against the same compiler with `-Zohm-stable-cgu-merging=no`. Both arms use identical source, PGO/BOLT profiles, defaults outside this policy, and eight jobs. Each project has two complete pairs, one in each arm order, with private empty targets/shared stores before the cold command. The five commands are the frozen affected library builds on Ruff, uv, and Codex: cold, no-op, and builds after original Edits 1, 2 and 3. The third uv edit may be inactive for the selected library build.

All six accepted pairs passed the original quiet windows, continuous guard, source/lock checks, command status, parity, and positive release. A rejected zero-command first Ruff attempt remains archived and is excluded. These are two samples per arm/state; medians and ranges describe this screen and are not confidence intervals.

Edits 1, 2 and 3 follow each project’s recorded source history in order. Ruff simplifies recursive attribute inference, indexes implicit attribute dependencies, then adds component fixed points. uv implements the dedicated Simple API JSON parser, simplifies its implementation, then simplifies compatibility tests. Codex adds transcript layout bookkeeping, implements stable active-cell rendering and snapshots, then invalidates cached layouts when active cells are removed. Each state retains the previous edits; the third uv edit may be inactive for the selected library commands.

## Command time

Seconds are command wall time. Percentages compare removal against full within each fixed pair; positive means removal was slower. The last two columns preserve the two orders separately.

| Project | State | Full median [range], s | Stable off median [range], s | Median change, s | Pair 0 | Pair 1 |
|---|---|---:|---:|---:|---:|---:|
| ruff | Cold build | 69.389 [66.029, 72.749] | 64.491 [64.387, 64.596] | -4.897 | -11.21% | -2.49% |
| ruff | Warm no-op | 0.883 [0.450, 1.317] | 0.731 [0.426, 1.036] | -0.152 | -21.30% | -5.41% |
| ruff | Edit 1 | 25.676 [23.520, 27.832] | 23.687 [23.238, 24.135] | -1.990 | -16.51% | +2.62% |
| ruff | Edit 2 | 34.225 [32.898, 35.552] | 32.707 [32.654, 32.760] | -1.518 | -7.85% | -0.74% |
| ruff | Edit 3 | 39.176 [39.147, 39.206] | 38.057 [37.219, 38.894] | -1.120 | -5.07% | -0.65% |
| uv | Cold build | 66.688 [66.103, 67.272] | 64.703 [63.903, 65.504] | -1.984 | -5.01% | -0.91% |
| uv | Warm no-op | 1.149 [1.144, 1.153] | 1.178 [1.080, 1.276] | +0.030 | -5.56% | +10.65% |
| uv | Edit 1 | 8.887 [8.847, 8.928] | 8.712 [8.506, 8.919] | -0.175 | -0.10% | -3.85% |
| uv | Edit 2 | 6.929 [6.838, 7.019] | 6.733 [6.520, 6.945] | -0.196 | -4.65% | -1.05% |
| uv | Edit 3 | 7.184 [6.654, 7.714] | 7.259 [6.903, 7.615] | +0.075 | +3.73% | -1.28% |
| codex | Cold build | 237.017 [230.893, 243.140] | 232.016 [231.918, 232.114] | -5.001 | -4.53% | +0.44% |
| codex | Warm no-op | 2.335 [2.325, 2.345] | 2.378 [2.336, 2.420] | +0.043 | +3.21% | +0.49% |
| codex | Edit 1 | 18.552 [17.902, 19.202] | 20.026 [19.737, 20.315] | +1.474 | +2.79% | +13.48% |
| codex | Edit 2 | 15.471 [15.338, 15.604] | 17.126 [16.627, 17.626] | +1.655 | +8.40% | +12.96% |
| codex | Edit 3 | 14.379 [14.316, 14.442] | 14.280 [14.210, 14.349] | -0.099 | -0.74% | -0.64% |

## Maximum child RSS

MiB from GNU time for each command. This is the maximum RSS of a child process, not the sum of simultaneously running compiler processes.

| Project | State | Full median [range], MiB | Stable off median [range], MiB |
|---|---|---:|---:|
| ruff | Cold build | 3325.334 [3267.688, 3382.980] | 3278.027 [3275.133, 3280.922] |
| ruff | Warm no-op | 61.510 [61.383, 61.637] | 61.512 [61.387, 61.637] |
| ruff | Edit 1 | 3537.926 [3455.008, 3620.844] | 3414.545 [3368.492, 3460.598] |
| ruff | Edit 2 | 4338.158 [4298.316, 4378.000] | 4260.660 [4240.129, 4281.191] |
| ruff | Edit 3 | 4458.885 [4449.113, 4468.656] | 4311.035 [4303.750, 4318.320] |
| uv | Cold build | 974.154 [967.344, 980.965] | 983.793 [978.805, 988.781] |
| uv | Warm no-op | 91.492 [91.375, 91.609] | 91.613 [91.605, 91.621] |
| uv | Edit 1 | 988.893 [984.875, 992.910] | 970.090 [958.828, 981.352] |
| uv | Edit 2 | 902.875 [902.066, 903.684] | 894.150 [890.648, 897.652] |
| uv | Edit 3 | 915.727 [912.324, 919.129] | 904.283 [903.195, 905.371] |
| codex | Cold build | 3363.062 [3356.016, 3370.109] | 3332.762 [3323.871, 3341.652] |
| codex | Warm no-op | 183.934 [183.824, 184.043] | 184.244 [184.156, 184.332] |
| codex | Edit 1 | 3797.918 [3780.594, 3815.242] | 3809.529 [3809.297, 3809.762] |
| codex | Edit 2 | 3040.254 [3036.094, 3044.414] | 3078.623 [3077.746, 3079.500] |
| codex | Edit 3 | 2673.102 [2672.406, 2673.797] | 2724.715 [2718.660, 2730.770] |

## Provenance and limits

The timing host was `charlie-serc-1`, boot `436143a7-77ff-4261-abf8-28b5287046f0`, with 32 CPUs and the scratch task root. The schedule is `7742f5af93e155f6cef57eb78d2a6dae3d4b60dd4acecedc2def3941cb4a0a7f`; measurement identity is `c169c451ee2e57f7119722af6aafeae64847ae2e1d91927ace0282c524579821`. The accepted baseline is the D3 69,859-file manifest. Existing native CGU/uv activation evidence was reused; this screen ran no native tests or compiler training.

Readiness reused the accepted baseline byte map and profile bodies. Its current metadata was verified on the host by the pinned collector's inode/size/mode checks; those current metadata bodies were not independently retrieved as part of the small readiness packet. The final command audit explicitly retains that boundary. All recorded command/supervisor identities and groups, collectors/readers, task users, leases, and compilers were positively closed after raw retrieval.

The independent caller-local and both-off screens ran on other hosts. These within-comparison deltas must not be added together or interpreted as a factorial interaction. Two opposite orders also cannot rule out all machine drift or explain why cold builds prefer removal while some edited builds prefer retention.

[Final root evidence review](stable-final-root-review-01.json), [machine-readable results](stable-off-detailed-results.json), [raw packet](complete-raw-retrieved-ssh-01/packet/validation/cgu-stable-serc1-complete-01/packet.json), [final current closure](final-current-release-actual-dbox-01/stdout.txt). The raw archive is 91,755,932 bytes, SHA-256 `5f912b74a2955848acf0721dac7e826c4274403b91141df244fc38ca99d2a2ad`; its 715 indexed payloads preserve their original bytes and modes.
