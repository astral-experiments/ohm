Disabling both CGU policies together is not a good simplification. Codex builds after each of the three edits took about 1.00, 1.45, and 1.59 seconds longer, respectively, and each regression appeared in both arm orders. The small cold-build savings do not offset that result. Decisions about each policy still depend on its separate ablation.

This screen used the same accepted optimized compiler and profiles in both arms on charlie-serc-direct-2, a 32-CPU Linux devbox, with eight build jobs. The full arm retained Ohm defaults. The other arm set `-Zohm-caller-local-cgus=no -Zohm-stable-cgu-merging=no`. Each project had two independent histories, one in each arm order. Every command used `cargo build --locked --offline --lib`; selected packages were `ty_python_semantic` and `ty_python_core`, `uv-pypi-types` and `uv-client`, and `codex-tui`.

Edits 1, 2 and 3 follow each project’s recorded source history in order. Ruff simplifies recursive attribute inference, indexes implicit attribute dependencies, then adds component fixed points. uv implements the dedicated Simple API JSON parser, simplifies its implementation, then simplifies compatibility tests. Codex adds transcript layout bookkeeping, implements stable active-cell rendering and snapshots, then invalidates cached layouts when active cells are removed. Each state retains the previous edits; the third uv edit may be inactive for the selected library commands.

These are two-pair screening results. The brackets show the observed range, not a confidence interval. Paired percentages preserve the two fixed orders; a positive value means removing both policies was slower. Absolute measurements from the other CGU hosts must not be pooled here, and the separate deltas must not be added to infer an interaction.

| Project | State | Full seconds, median [range] | Both off seconds, median [range] | Paired change, slot 0 / slot 1 |
|---|---|---:|---:|---:|
| ruff | Cold build | 55.712 [53.509, 57.916] | 54.208 [53.202, 55.214] | -4.67% / -0.57% |
| ruff | Warm no-op | 0.457 [0.413, 0.502] | 0.397 [0.388, 0.406] | -22.64% / -1.85% |
| ruff | Edit 1 | 21.276 [21.219, 21.333] | 21.735 [21.544, 21.926] | +2.78% / +1.53% |
| ruff | Edit 2 | 27.722 [27.527, 27.917] | 27.387 [27.101, 27.674] | -0.87% / -1.55% |
| ruff | Edit 3 | 31.779 [31.455, 32.102] | 31.964 [31.894, 32.034] | -0.21% / +1.40% |
| uv | Cold build | 50.978 [50.065, 51.890] | 51.667 [51.096, 52.239] | -1.53% / +4.34% |
| uv | Warm no-op | 0.732 [0.632, 0.832] | 0.810 [0.704, 0.916] | +10.15% / +11.45% |
| uv | Edit 1 | 7.246 [7.201, 7.291] | 6.990 [6.968, 7.013] | -4.43% / -2.61% |
| uv | Edit 2 | 5.070 [4.990, 5.151] | 5.443 [5.072, 5.813] | +12.86% / +1.66% |
| uv | Edit 3 | 5.441 [5.192, 5.691] | 5.615 [5.412, 5.819] | +12.08% / -4.90% |
| codex | Cold build | 197.161 [195.941, 198.381] | 194.703 [194.178, 195.227] | -1.59% / -0.90% |
| codex | Warm no-op | 2.127 [2.083, 2.170] | 2.082 [2.051, 2.112] | +1.40% / -5.49% |
| codex | Edit 1 | 15.490 [15.461, 15.519] | 16.488 [15.908, 17.068] | +2.89% / +9.99% |
| codex | Edit 2 | 14.375 [14.364, 14.385] | 15.821 [15.333, 16.309] | +13.37% / +6.74% |
| codex | Edit 3 | 12.418 [12.304, 12.533] | 14.006 [13.964, 14.047] | +14.17% / +11.42% |

Memory is GNU time maximum child-process RSS. It does not measure the sum of concurrently running compiler processes. Values below are medians and observed ranges in MiB.

| Project | State | Full RSS, median [range] | Both off RSS, median [range] |
|---|---|---:|---:|
| ruff | Cold build | 3391.598 [3380.070, 3403.125] | 3470.924 [3462.020, 3479.828] |
| ruff | Warm no-op | 61.637 [61.629, 61.645] | 61.762 [61.637, 61.887] |
| ruff | Edit 1 | 3621.713 [3609.297, 3634.129] | 3610.797 [3607.621, 3613.973] |
| ruff | Edit 2 | 4383.939 [4370.289, 4397.590] | 4449.857 [4441.262, 4458.453] |
| ruff | Edit 3 | 4444.703 [4439.672, 4449.734] | 4532.328 [4529.457, 4535.199] |
| uv | Cold build | 984.666 [982.184, 987.148] | 1000.195 [996.129, 1004.262] |
| uv | Warm no-op | 91.730 [91.605, 91.855] | 91.740 [91.613, 91.867] |
| uv | Edit 1 | 980.455 [973.457, 987.453] | 978.365 [964.797, 991.934] |
| uv | Edit 2 | 897.051 [889.945, 904.156] | 885.986 [874.598, 897.375] |
| uv | Edit 3 | 903.721 [899.168, 908.273] | 901.740 [893.859, 909.621] |
| codex | Cold build | 3375.354 [3363.375, 3387.332] | 3357.846 [3340.234, 3375.457] |
| codex | Warm no-op | 184.049 [183.977, 184.121] | 184.209 [183.961, 184.457] |
| codex | Edit 1 | 3823.277 [3823.168, 3823.387] | 3579.279 [3572.637, 3585.922] |
| codex | Edit 2 | 3068.066 [3065.582, 3070.551] | 3137.580 [3128.859, 3146.301] |
| codex | Edit 3 | 2673.947 [2670.055, 2677.840] | 2789.734 [2784.531, 2794.938] |

The [final independent audit](cgu-both-final-root-review-01.json) accepted all six pairs, 60 timed commands, 15 command-state summaries, 1,655 continuous samples, and 144 required quiet samples. All 723 indexed raw payloads, original modes, 58 readiness proofs, exact runtime flags, and final ownership releases passed. The [raw packet](complete-raw-retrieved-ssh-01/packet/validation/cgu-both-direct2-complete-01/packet.json) binds the archive `1b88a89f26e7de717294e5fc66d6e2b6baf390990cf5c811a5cb010ed81dd962`. The [final current closure](final-current-release-actual-ssh-01/stdout.txt) separately proves all 12 recorded command/supervisor identities and task users closed. No new compiler build, training, or native-suite execution was needed for this screen.
