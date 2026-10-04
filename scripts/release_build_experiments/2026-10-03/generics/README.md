# Sharing optimized generics in release builds

This experiment measures Cargo's opt-in `-Zohm-lto-share-generics` policy. It passes `-Zshare-generics=yes` to optimized final LTO units and dependencies used only as LTO bitcode. Host tools and dependencies shared with non-LTO consumers are excluded. Defaults remain unchanged.

The actual-policy comparison uses the **same compiled Cargo executable** with the option disabled and enabled. The earlier global `RUSTFLAGS` screening cohort is separate and must not be substituted for these results.

## Pinned inputs

| Input               | Revision                                               |
| ------------------- | ------------------------------------------------------ |
| Ohm distribution    | `ohm-1.99.0-1`                                         |
| rustc               | `348339ddae4288ebb3af97d204b19479fef8f5f2`             |
| Released Cargo/base | `018a2b93409433dc5bc05c5fce838ae69e9bc396`             |
| Candidate Cargo     | `cbec67aa6ad824fdb8550d033bfd0aee0787b1b5`             |
| uv                  | `46b84fd0bfec23b72f29e8e2185ba68a65052f48`             |
| Ruff                | `1df6db3e463ffa1b587dcf47f25360d40389b0f7`             |
| CPython             | `0b05ead877f909b7efe712db758012d9dbece7ce` (`v3.12.7`) |

Linux distribution archive SHA256: `ed158e6fbd2170cfd29af0dfc38cb0f9be0a23159a61914c9c49e0cd34342f71`. Compiler ELF SHA256: `b6b19fee2a00fd842b7c97876afec154e2c4eac985f315b0294de9780fd10452`.

Build the pinned Cargo source using the exact Ohm toolchain, `--locked --release --features ohm-defaults --bin cargo`, with separate target and build directories. The source archive used for the campaign has SHA256 `92075acfc30dbb352a28462f667009e77c799918282301465c5586e312c2c93d`. Its generated `git-commit-info` contains the candidate's full hash, short hash `cbec67aa6`, and date `2026-10-03` on separate lines. The Cargo binary built on `charlie-serc-1` and copied to both 16-CPU hosts has SHA256 `f36feba8fa901468fd4469890b516270b9f97acfc783dc90f21fc48dd07b3a7f`. The independently built Cargo on `charlie-serc-3` has SHA256 `7e53d3d05f56722cd5db7f8073ab069050d6606bd4b50820c524367656ece38a`. Every off/on pair uses the same executable within its host. Each sample records the actual Cargo and compiler hashes.

All four hosts report AMD EPYC-Milan processors with one thread per exposed core. The serc hosts expose 32 CPUs and the openai hosts expose 16 CPUs. Each process has the full CPU affinity, no cgroup CPU quota, and no cgroup memory limit; exact cgroup paths and machine memory snapshots remain in raw records.

## Build measurements

Use clean pinned checkouts. Fetch locked registry sources before timing. Start with at least 30 GiB free. Run one measurement process per host, at the host's default Cargo concurrency; the runner removes job-count and release-profile environment overrides. It records CPU model, affinity, cgroup limits, compiler identity, command arguments, source hashes, binary sizes, GNU time output, Cargo timing reports, and continuous outside-process CPU observations.

For example, with the pinned uv checkout, compiled Cargo executable, and an existing empty results root:

```sh
python3 ablate.py --repo /path/to/uv --name uv \
  --toolchain ohm-1.99.0-1 --cargo-bin /path/to/candidate-cargo \
  --lto fat --share default --sample 1 --root /path/to/results/HOST/policy \
  --cargo-home /path/to/public-cargo-home --discard-builds --library-edit
python3 ablate.py --repo /path/to/uv --name uv \
  --toolchain ohm-1.99.0-1 --cargo-bin /path/to/candidate-cargo \
  --lto fat --share policy --sample 1 --root /path/to/results/HOST/policy \
  --cargo-home /path/to/public-cargo-home --discard-builds --library-edit
```

Repeat in reverse order for the next pair. Ruff uses `--name ruff`; ThinLTO uses `--lto thin`. Both projects normally use fat LTO for these release builds. ThinLTO rows are a separate profile experiment.

Each invocation measures:

1. A build with empty, isolated Cargo target and build directories. Registry downloads and OS file caches are warm; this does not claim a cold disk or cold precompiled standard library. Ohm's compiled registry/workspace namespaces reside inside the isolated build directory.
2. A binary entry-point edit that adds `black_box` of a string.
3. A generic deserializer error-message edit in `uv-normalize` or `ruff_text_size`, on top of the entry-point edit.

The runner restores source bytes, saves each executable, retains logs, and deletes only that sample's owned target/build directories after all stages succeed. Runtime checks use the unedited cold executable.

Some v3 preflights refused edit stages while system activity reduced CPU idle below 95%. All refusals are retained, and completed cold or edit measurements were preserved. v4 adds `--resume`, validates identical source/commands/environment/compiler hashes, preserves the original checkpoint, records rejected preflights and per-stage runner hashes, and waits up to two minutes for idle before timing. Active v3 invocations were not modified. Both frozen versions are provided; resumed stages must retain their individual provenance.

## Runtime and correctness

`runtime.py` is the frozen timing program; `run-runtime.py` adds only this trusted experiment directory to Python's import path for devboxes configured with `PYTHONSAFEPATH=1`. It records the wrapper and imported helper hashes and leaves the measured program and child environment unchanged. `runtime.py` uses three warmups per binary/workload and 30 paired measured repetitions in deterministic shuffled order. Run it only after compile work on that host finishes. For uv, place the pinned checkout under a sources root named `uv` and pass an isolated cache:

For exact helper provenance, create a separate runtime directory, copy `runtime.py` and `run-runtime.py` there, then copy each helper listed for the desired host in `runtime-helpers.json` into that directory under its recorded name. The manifest points to preserved source files under `runtime-helpers/`; do not substitute the latest build runner. The measured runtime helpers use identical process-monitoring functions. Older versions differ in cgroup metadata collection and an inactive command-line routing shim; complete ancestor-cgroup metadata is also recorded by the build cohort. Run the following command from that runtime directory:

```sh
python3 run-runtime.py --name uv \
  --baseline /path/to/results/HOST/policy/uv-fat-default-1/uv-cold \
  --candidate /path/to/results/HOST/policy/uv-fat-policy-1/uv-cold \
  --sources /path/to/sources --output /path/to/results/HOST/policy/uv-runtime-1 \
  --cache /path/to/uv-runtime-cache --runs 30
```

uv resolves its pinned `test/requirements/trio.in` and `jupyter.in` inputs for Python 3.12, with an October 1, 2026 cutoff. An untimed network setup warms a public PyPI cache; measured runs are offline and remove the output file each time. Requirements hashes must match.

Ruff checks and formats the entire pinned `CPython/Lib` tree with `--isolated --no-cache`. Checks use concise output and `--exit-zero`. Formatting uses `--check`; expected status 2 reflects intentionally invalid syntax fixtures in this corpus. This measures both valid-file formatting and fixture error handling. Both variants must produce identical output and diagnostics with the same expected status.

Run `runtime-audit.py` on the complete raw results before interpreting runtime numbers. It requires exact status and stdout equality. For Ruff check, it validates the exact multiset of the two known warnings before allowing their order to differ; formatter stderr must be empty. For uv, it removes only the duration in the anchored `Resolved N packages in <duration>` line and retains package counts and all warning/diagnostic text. Original stdout/stderr bytes remain in the evidence archive.

Use `audit-scope.py` on verbose build logs to validate injected compiler flags. `summarize.py` retains individual build times, within-host ratios, all preflight refusals, resume checkpoint hashes, and stage-specific runner identity. Compare ratios within each host; do not pool raw wall times from 16- and 32-CPU machines. Single-pair ThinLTO screens are exploratory until repeated.

For analysis, place each host under `results/HOST/` with actual-policy sample directories under `policy/` (the commands above use this layout). Write the post hoc runtime audit to `results/HOST/runtime-audit.json`, then pass the overall `results` root to `summarize.py`. The summary reads GNU time user/system CPU, reported wall time, page faults, and maximum RSS directly from each stage log, preserving its SHA256. For this campaign's separately extracted archives, pass `--raw-root /path/to/raw`; it expects `raw/HOST/results/policy/SAMPLE/STAGE.log`. Maximum RSS is GNU time's process/child high-water figure and does not measure aggregate concurrent compiler memory.

Original result, compiler-log, and archive SHA256 fields identify the unmodified bytes retained in the raw host archives. They do not identify the formatted compact JSON or Markdown files checked into the evidence report. Publication-file hashes are computed separately after formatting; measured Python sources are preserved byte for byte.

Ruff's formatter emits an identical 34 MB stdout capture repeatedly. Its archive stores each unique capture once and uses tar hard links for matching content hashes and byte lengths. Every original path, length, and SHA256 remains in the manifest; remote capture files remain unchanged. Local verification reconstructs these paths with hard links only inside the task-owned raw directory. `archive-index.json` records this representation separately from the measured bytes.
