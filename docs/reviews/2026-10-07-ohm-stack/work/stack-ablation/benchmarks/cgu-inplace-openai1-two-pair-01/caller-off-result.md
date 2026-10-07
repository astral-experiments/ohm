# Caller-local CGU policy ablation

**Recommendation: remove the 26-line policy.** Removal improved both measured cold Codex builds, saving a two-pair median of 15.182 seconds. It also improved both Codex builds after Edits 1 and 3, by 0.548 and 2.103 seconds. Those results, and the goal of reducing divergence from upstream, support removal.

Retaining the policy helps other edited builds. Turning it off slowed both Ruff builds after Edit 1 by a median 2.838 seconds, both Ruff builds after Edit 2 by 0.927 seconds, and both uv builds after Edit 1 by 0.860 seconds. These costs should remain part of the removal decision. The cold uv builds favored removal by 2.687 seconds in both orders.

This screen measures one accepted optimized compiler with its normal policies against that same compiler with `-Zohm-caller-local-cgus=no`. It validates the runtime policy comparison; pruning the corresponding source has not yet been validated. Both arms use identical source, PGO/BOLT profiles, other defaults, and eight jobs. Each project has two complete pairs, one in each arm order, with independent empty target/shared histories.

The five selected library build commands are cold build, warm no-op, and builds after original Edits 1, 2 and 3. All three frozen original edits are applied; uv’s third edit may not affect its selected library. Command time excludes setup, quiet waits, source-proof collection, and cleanup. These are two samples per state and arm. Ranges describe this screen and are not confidence intervals.

Edits 1, 2 and 3 follow each project’s recorded source history in order. Ruff simplifies recursive attribute inference, indexes implicit attribute dependencies, then adds component fixed points. uv implements the dedicated Simple API JSON parser, simplifies its implementation, then simplifies compatibility tests. Codex adds transcript layout bookkeeping, implements stable active-cell rendering and snapshots, then invalidates cached layouts when active cells are removed. Each state retains the previous edits; the third uv edit may be inactive for the selected library commands.

## Command time

Seconds are command wall time. Each percentage compares removal against full within its fixed pair; positive means removal was slower.

| Project | State | Full median [range], s | Caller off median [range], s | Median change, s | Pair 0 | Pair 1 |
|---|---|---:|---:|---:|---:|---:|
| ruff | Cold build | 66.125 [65.401, 66.849] | 65.961 [65.171, 66.752] | -0.164 | -0.15% | -0.35% |
| ruff | Warm no-op | 0.447 [0.438, 0.456] | 0.720 [0.707, 0.734] | +0.274 | +61.34% | +61.12% |
| ruff | Edit 1 | 26.492 [26.325, 26.660] | 29.331 [28.766, 29.896] | +2.838 | +7.90% | +13.57% |
| ruff | Edit 2 | 33.718 [32.923, 34.513] | 34.645 [34.465, 34.825] | +0.927 | +4.68% | +0.90% |
| ruff | Edit 3 | 38.509 [38.421, 38.597] | 38.337 [37.890, 38.784] | -0.171 | -1.38% | +0.49% |
| uv | Cold build | 65.493 [63.726, 67.260] | 62.806 [62.210, 63.403] | -2.687 | -5.73% | -2.38% |
| uv | Warm no-op | 0.731 [0.574, 0.888] | 0.623 [0.552, 0.695] | -0.108 | -37.91% | +21.07% |
| uv | Edit 1 | 8.390 [8.298, 8.481] | 9.249 [8.715, 9.784] | +0.860 | +5.01% | +15.37% |
| uv | Edit 2 | 5.495 [5.462, 5.527] | 5.367 [5.352, 5.382] | -0.128 | -2.01% | -2.63% |
| uv | Edit 3 | 6.222 [5.541, 6.904] | 5.446 [5.306, 5.586] | -0.777 | +0.82% | -23.15% |
| codex | Cold build | 257.259 [244.801, 269.717] | 242.077 [240.356, 243.798] | -15.182 | -9.61% | -1.82% |
| codex | Warm no-op | 4.893 [3.733, 6.053] | 3.810 [3.143, 4.477] | -1.083 | -26.04% | -15.81% |
| codex | Edit 1 | 19.672 [19.551, 19.793] | 19.124 [18.879, 19.368] | -0.548 | -3.44% | -2.14% |
| codex | Edit 2 | 14.926 [14.533, 15.319] | 14.415 [14.219, 14.611] | -0.511 | +0.53% | -7.18% |
| codex | Edit 3 | 15.214 [15.054, 15.374] | 13.111 [13.016, 13.206] | -2.103 | -12.27% | -15.34% |

## Maximum child RSS

MiB from GNU time for each command: maximum child-process RSS, not the sum of simultaneous compiler processes.

| Project | State | Full median [range], MiB | Caller off median [range], MiB |
|---|---|---:|---:|
| ruff | Cold build | 3374.203 [3327.355, 3421.051] | 3636.928 [3635.367, 3638.488] |
| ruff | Warm no-op | 61.986 [61.906, 62.066] | 61.924 [61.785, 62.062] |
| ruff | Edit 1 | 3578.529 [3548.738, 3608.320] | 3864.283 [3832.438, 3896.129] |
| ruff | Edit 2 | 4366.676 [4366.656, 4366.695] | 4523.160 [4511.980, 4534.340] |
| ruff | Edit 3 | 4384.045 [4369.805, 4398.285] | 4665.945 [4662.520, 4669.371] |
| uv | Cold build | 980.973 [974.488, 987.457] | 991.777 [990.988, 992.566] |
| uv | Warm no-op | 91.609 [91.539, 91.680] | 91.861 [91.805, 91.918] |
| uv | Edit 1 | 971.211 [963.145, 979.277] | 970.713 [970.535, 970.891] |
| uv | Edit 2 | 909.281 [907.297, 911.266] | 894.814 [893.270, 896.359] |
| uv | Edit 3 | 913.336 [905.023, 921.648] | 907.441 [907.125, 907.758] |
| codex | Cold build | 3377.996 [3371.117, 3384.875] | 3346.535 [3340.422, 3352.648] |
| codex | Warm no-op | 183.795 [183.734, 183.855] | 184.139 [184.078, 184.199] |
| codex | Edit 1 | 3818.842 [3817.145, 3820.539] | 3840.242 [3836.656, 3843.828] |
| codex | Edit 2 | 3066.184 [3056.172, 3076.195] | 3005.070 [3001.152, 3008.988] |
| codex | Edit 3 | 2672.744 [2668.609, 2676.879] | 2636.111 [2633.277, 2638.945] |

## Provenance and limits

Ruff and uv each ran both orders on `charlie-openai-1`, a 16-CPU host, boot `321ccc0d-75af-4b43-88b8-33d419026f5c`. Codex’s two prospective orders ran on `charlie-serc-314-o1`, a 32-CPU host, boot `3f7fc3b3-198d-40d3-b086-de2927af8f65`. Within-project deltas are valid. Absolute results are not pooled across hosts, and these policy screens do not establish a factorial interaction or justify adding deltas from the separate stable and both-off comparisons.

The original four Ruff/uv pairs passed the original quiet windows, continuous guard, source/lock checks, parity, actual command status, and positive release. Two rejected initial Ruff pairs and three rejected Codex attempts on the original host remain archived and excluded. The replacement Codex block contains two fresh complete accepted pairs; it imports no commands from rejected attempts.

The accepted runtime is the same D3 69,859-file map in both arms, with b134 shipping provenance and the accepted native/activation evidence. The initial host-bound metadata checks are assertions of the pinned collector against prior accepted byte maps; they are not presented as independently retrieved current runtime binaries. The original native activation has its declared branch-hit limitations.

Raw blocks: [original Ruff/uv evidence](original-four-raw-retrieved-ssh-01/packet/README.md) and [prospective Codex evidence](codex-only-resident-migration-01/complete-raw-retrieved-ssh-01/packet/README.md). Exact accepted paths and result hashes are listed in [the detailed data](caller-off-detailed-results.json). Final root acceptance is recorded in [the complete review](caller-final-root-review-01.json) (`b179d75ffb23b414330a4f03333eee8613a6d2837f69d450a4d710e090076574`). It covers six complete pairs, 60 command results, 15 states, 1,784 continuous samples, 144 required quiet samples, and the 18 original plus four replacement final ownership identities.
