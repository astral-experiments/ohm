# Production uv #20988 root check

This private, unscored registration measures one ordinary `cargo check --locked --offline -j8` at the uv workspace root immediately after applying the real upstream edit. The edit changes workspace-exclusion behavior in `uv-workspace` and its discovery benchmark. The checkout retains the actual parent HEAD and index. Its working tree becomes the exact landed child. [uv #20988](https://github.com/astral-sh/uv/pull/20988)

| Arm | Rust commit | Rust tree | Cache epoch |
|---|---|---|---:|
| Corrected stock | `10d56274a98801b5ef8f80aab734e835749458e1` | `1a0e58a855e1782a93cdf8c56b337fb4354142ef` | 43310 |
| Corrected #296 + #306 | `4cc83ad906d8cd570c15b4508bc82ec3712cfb81` | `cb977189205aa931f080b57b9a8bb62ef98a316e` | 43309 |

Both production recipes include the #318 CTFE allocation correction. Each uses its own fully qualified GNU PGO+BOLT compiler and standard library. Only the Cargo executable is overlaid. Its official signed −22 SHA-256 is `3ce4e300d4463dfc769b6c18e138d1c951b02dfb15416a39cb5301303d168871`. The previous stage1 experiment used different compiler binaries.

## Admit a completed build

The two standard Namespace build workers belong to first-attempt run 41374825846 at cddb036d81e4313a8e422171f39f0840b44110db. Its registered producer SHA-256 is 4ee933fe558a1f3cea9bb095c71fe51888bddd060507541c88d1d95870f3065f. Each worker must pass the precommitted 250 GiB workspace floor, physical reserve and six-stage capacity readback. Inspect the run only after all three jobs succeed. From an OSS checkout with the verified `charliermarsh` identity, read the run, its attempt-one job listing and artifact listing from these GitHub API endpoints using `gh-auto api`.

```text
repos/astral-experiments/ohm/actions/runs/BUILD_RUN
repos/astral-experiments/ohm/actions/runs/BUILD_RUN/attempts/1/jobs?per_page=100
repos/astral-experiments/ohm/actions/runs/BUILD_RUN/artifacts?per_page=100
```

Save the three unmodified JSON objects as `run.json`, `jobs.json`, and `artifacts.json`. This command needs Python 3.11 or newer and uses no network.

```sh
python3 -ISB enroll.py lock run.json jobs.json artifacts.json > sdk-lock.json
sha256sum sdk-lock.json
```

Review the resulting five distinct IDs and digests, the private repository, exact head, producer workflow and three successful job IDs. The hosted intake fetches all five ZIPs anew, rechecks their service lengths/digests, authenticates the original pair QA and two-way cache migration, reruns the producer's entire inventory reader, verifies the actual PGO/BOLT and regression logs, then extracts only the exact Cargo executable from the separately attested signed −22 release. A failed/missing build, expired ZIP, changed source, incomplete migration, or unregistered third compiler prevents enrollment.

## Private Actions placement

Place `workflow.yml` at `.github/workflows/ci.yml` and the other files, including `SHA256SUMS`, under `scripts/uv-20988-ctfe-hw/` on the dedicated `charlie/codex-20988-ctfe22-root-hardware` branch. The four required workflow inputs are the reviewed benchmark head, qualified build run ID, reviewed build head and the enrolled SDK-lock digest. The workflow runs once on one private 16-vCPU Namespace runner and selects eight distinct physical cores. Only the artifact admission step receives the repository read token. The Cargo workload receives the exact closed environment recorded in `protocol.json`.

## What is timed and counted

* Parent `b60da7ad468d5bb8a6b3dee7d7e54a47981f23c7` and child `1979349b68dbaa936b98c0f409c1df0598fa72f1` are authenticated by commit, tree, 15-commit tag-to-child history, two changed paths, full binary diff and unchanged Cargo.lock. All 658 registry archives and their sparse-index rows must match. The preparatory Cargo fetch runs once, before qualification.
* Each role must pass actual A, independently warm A→B, and two clean B builds, with the exact original positive and negative downstream source/type witnesses. The upstream `workspace::tests::exclude_package` filter must select one passing test at A and both passing tests at B. No test execution is timed.
* The 12 pairs and both six-pair holdouts are fixed in `protocol.json`. Each hold has three stock-first and three stack-first pairs. Every arm gets a genuinely new A build and its own settled snapshot. An independently restored edit is used for ordinary wall, inherited userspace hardware instructions, Cargo diagnostic output and child-process tracing. The first two visits are counterbalanced. Source, Git state, target, registry, home, per-file content/mode/mtime, and on-disk incremental headers must match the frozen A before every edit. PMU observer time is never scored as native wall.
* The inherited PMU must pass all 28 fork, exec and thread calibrations, then report positive userspace instructions and exact enabled/running equality. A separately restored uninstrumented Cargo child is stopped by the kernel on successful exec to read the genuine compiler process and its complete original argv. All 18 rustc invocations must exactly match the raw direct Cargo verbose journal and the pre-existing reference.
* Each same-seed visit must reproduce all 70 workspace library metadata files byte-for-byte. Across independent cold histories, the reader compares all 70 public/private crate hashes, IDs and full dependencies plus real downstream consumer outcomes. It deeply compares every differing raw product and always the terminal library. This includes complete definition keys/descriptors/fingerprints, reachable expansions and allocation record contents, multiplicities and order. A missing key, changed allocation, undecodable difference or unknown target prevents scoring. Raw bytes of the qualifying and timed ordinary visits are retained.
* The independent reader rebuilds eligibility from the service metadata, original Cargo transcripts, successful kernel exec records and process ancestry, raw metadata archives, complete effective SDK inventories and raw clocks. The result includes every order, pair and raw value. Ratios use corrected stock divided by corrected #296+#306. Separate paired medians for wall and instructions use the order-statistic interval from the second through eleventh ratio, with 99.365234375% nominal per-metric median coverage under independent matched signs. Passing 2× requires the lower endpoint, both holdout medians and both order-stratum medians to exceed 2. The panel measures this one calibrated host. The two measures can have different outcomes.

The run has 30 cold workspace builds, four independently targeted fixture builds, and four edited visits for each of 24 measured arm/seed combinations. If capacity, the 350-minute job limit, raw replay or any guard fails, preserve the partial artifact and report the incomplete attempt. A completed panel and its raw archive are required for a result.

## Recalculate from the artifact

After downloading and verifying the service artifact digest, invoke the following with the result directory and the authenticated `scripts/uv-root-20991-opening` folder from Ohm commit `341cd92e5d381a50bd380467075f31e780ee6296`. It reopens raw source/semantic receipts, all actual child exec records and recorded clocks without running a compiler or using an SDK.

```sh
python3 -ISB audit.py /absolute/path/to/trait-results /absolute/path/to/scripts/uv-root-20991-opening
```

The marginal immutable-reference experiment needs its own reviewed artifact contract, true behavior and cross-version admission, new role order and a fresh 12-pair run comparing it to this exact combined artifact. The paired estimator accepts separately registered role/order arguments. The two-role intake here rejects the third arm, and the controls reject assigning this existing panel to a marginal comparison.

This fresh admission uses the stock and trait production SDKs from standard-capacity run 41374825846 at cddb036d81e4313a8e422171f39f0840b44110db. It independently replays twelve raw capacity journals and matches both machines to their host and native SDK receipts. The five Actions artifact IDs and ZIP digests come from the successful first attempt. The real Cargo command runs under its unchanged environment in a separate Linux exec-stop observation, before any clocks and again from the same earlier cache as each timed pair. The wall and PMU commands retain the original full qualification and twelve-pair protocol.
