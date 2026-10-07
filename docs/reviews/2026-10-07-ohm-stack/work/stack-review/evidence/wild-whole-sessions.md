# Full Ohm session replays

This experiment measures whether the final Wild stack reduces time spent in recorded development sessions. It compares upstream Wild, the normal-release stack, and the stack built with the optional ThinLTO/PGO recipe.

**Result:** the completed uv and Ruff comparisons do not establish a workflow speedup. uv is inconclusive; Ruff shows a small slowdown with both stack builds on this host and fixture. Codex stopped on a harness validation failure and has no aggregate performance estimate.

## Results

Elapsed changes compare directly with upstream. Negative values mean less time. Brackets contain paired 95% bootstrap intervals.

| Session | Upstream mean | Normal stack mean | Normal stack change | ThinLTO/PGO mean | ThinLTO/PGO change |
| --- | ---: | ---: | ---: | ---: | ---: |
| [uv](results/whole-sessions-20260908/uv/README.md) | 152.32 s | 149.64 s | −1.76% [−6.72, +3.41] | 153.59 s | +0.83% [−0.47, +2.15] |
| [Ruff](results/whole-sessions-20260908/ruff/README.md) | 392.36 s | 395.37 s | +0.77% [+0.10, +1.62] | 395.15 s | +0.71% [+0.27, +1.28] |
| [Codex](results/whole-sessions-20260908/codex-incomplete/README.md) | Incomplete | — | — | — | — |

uv completed all 18 sessions with matching compilation counts and expected test results; an [independent audit](results/whole-sessions-20260908/support/uv-independent-audit.json) reproduced the statistics and reparsed the logs. Both comparisons with upstream are inconclusive. Its largest command, an installation integration test including its build, averages 78.75 seconds upstream; the test body reports about one second. The [command breakdown](results/whole-sessions-20260908/support/uv-command-characterization.json) does not separate compiler and linker time within that build.

Ruff completed all 18 sessions. Its [independent audit](results/whole-sessions-20260908/support/ruff-independent-audit.json) verified all 216 command logs and 54 edit logs, matching test and compilation counts, and independently reproduced the statistics. The normal stack takes 3.01 seconds more than upstream on average; ThinLTO/PGO takes 2.80 seconds more. Both intervals support a small slowdown in this experiment. The difference between the two stack builds is inconclusive. The [command breakdown](results/whole-sessions-20260908/support/ruff-command-characterization.md) found no test retries; build and test phases both contributed to the observed increases.

Codex started six of its planned 18 sessions. Five passed every validation gate; the sixth completed every fixture command but was rejected by the harness for a Git child exiting with status 1. All six full test commands reported 3,439 passed and 16 skipped, and all 420 recorded Wild workers exited successfully. The sixth session lacks the final source and artifact-identity checks. The failed receipt and all logs are retained; no Codex mean, interval, or partial-run speedup is reported.

These results do not support a 10% complete-session improvement. Individual PRs retain their separate evidence for link latency, CPU work, or memory use; the [PR value audit](results/endpoint-comparison-20260908/PR_VALUE_AUDIT.md) records those narrower benefits and tradeoffs.

## Workloads

The runner executes the Ohm fixture's commands and patches directly after its prescribed warmup, including every edit and command. Ohm's coordinator setup is outside the timed interval. The selected fixtures cover repeated source changes followed by focused tests, broader validation, and linting.

| Project | Fixture | Measured work |
| --- | --- | --- |
| uv | PyPI Simple API JSON parser | Three edits, eight test commands, three Clippy commands, three formatting checks |
| Ruff | Recursive attribute inference with component fixed points | Three edits, eight nextest commands, three Clippy commands, one formatting check |
| Codex | TUI active-cell transcript layout | Three edits, nine test commands, one Cargo check, one Clippy command |

The source revisions, patches, dependencies, profiles, test filters, and expected test counts are pinned. Codex retains the fixture's existing setup patch and exclusions. The experiment adds no test exclusions.

## Method

- Six rounds planned per project, with all six orders of the three linker builds used once. uv and Ruff completed the full budget; Codex stopped during round two. The order and sample count were fixed before timing.
- The same warm source and build snapshot is restored at the same paths before every session. A stable shim selects Wild through an environment variable. All three builds must pass a switch preflight without recompiling dependencies.
- Ohm Cargo/rustc 1.98.0-2, eight Cargo jobs, CPUs 8–15, the normal jobserver, and ext4 build artifacts. The host reports an AMD EPYC-Milan processor, 32 logical CPUs, and Linux 6.8.0-106.
- Primary elapsed time covers all fixture edits and commands. Checkout, preparation, warmup, snapshot restoration, synchronization, initial validation, and postflight checks are excluded. Command time is reported separately.
- The timed sessions contain no link tracing, capture, or extra relinks. Source states, lockfiles, tool and binary identities, expected test counts, and successful Wild worker exits are checked.
- Analysis resamples complete three-build rounds together, with 10,000 draws and seed 0. Intervals assume independent rounds and describe this host and fixture. Per-command comparisons are exploratory; intervals are not adjusted for multiple comparisons.

## Build identity and scope

Upstream is `96944c96cb7740235c97325860a7d3fea5257054`; the final stack is `29fa38b5e911e9e354bf7090f5f0930246707584`. The stack retains its original branch point, so this comparison also includes upstream commits made after that point.

All Wild binaries use Rust 1.97.1 and the controlled SmallVec 1.15.2 dependency override used in the earlier comparisons. The committed SmallVec 1.16.0 set remains unmeasured. Project dependencies follow their unchanged fixture lockfiles. The saved PGO executable maps to the final source through a documented lint-only difference and reuses the sealed training profile; normal-release versus PGO therefore compares ThinLTO and PGO together.

The earlier [14–20% improvements](results/endpoint-comparison-20260908/README.md) were for three representative isolated links with warm inputs and tmpfs output, using the ThinLTO/PGO stack. Whole-session results include compiler, Cargo, test, and lint work, and allow concurrent links to overlap. The stack's tmpfs-only page-population optimization is inactive in this ext4 experiment. These are different measured dimensions; the percentages cannot be substituted for one another.

These runs compare the ends of the stack. They do not measure any individual PR's incremental benefit to a complete session.

## Evidence and historical correction

Each completed project has a report, exact samples, raw command logs, preparation and preflight receipts, fixture inputs, source oracles, helper scripts, and a SHA-256 inventory under [the result directory](results/whole-sessions-20260908/). Large binaries, archives, and build trees are excluded from the repository bundle; receipts preserve their identities and original paths.

The stopped Codex run is archived separately as incomplete. Generated Cargo caches have been released, and the warm snapshots remain on local disk. [Preservation and cleanup receipts](results/whole-sessions-20260908/support/stop-support-index.json) map the temporary archive paths to their retained locations without rewriting historical evidence.

Codex preparation exposed two harness assumptions: its tests leave subprocesses with nonzero exits during teardown, and nextest writes a JUnit report inside the checkout. An untimed full fixture run verified all commands and test counts. The measured adapter recorded the generated report separately and permitted only the observed helper/status pairs. That finite list was too restrictive: the measured comparison later stopped on an unlisted Git exit status 1. This was a harness rejection after successful fixture commands. The exact Git invocation was not recorded, so its purpose is not inferred. The comparison was not resumed or reclassified; a revised adapter was drafted but never measured. Original failed preparation, diagnostics, and incomplete measurement evidence remain preserved separately.

The older four-session uv comparison restored a four-job cache into eight-job runs. Ohm Cargo uses different build-cache namespaces for those settings, so all four sessions rebuilt dependencies. Its reported 1.04% reduction describes those cache-miss runs. The [cache audit](results/actual-session/validation/warm-cache-lane-audit.json) preserves the evidence. The new experiment creates fresh warm snapshots with the actual measurement settings and verifies that switching linkers causes no recompilation.
