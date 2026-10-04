# Early fat-LTO merging experiment

This experiment retains the existing release optimization level, codegen-unit count, and fat-LTO setting. It adds `MergeFunctionsPass` at LLVM's `FullLinkTimeOptimizationEarly` extension point. The proposed compiler flag is disabled by default.

## Pins

- Ohm release: `ohm-1.99.0-1`, Rust `348339ddae4288ebb3af97d204b19479fef8f5f2`, Cargo `018a2b93409433dc5bc05c5fce838ae69e9bc396`.
- Shipping Linux archive SHA-256: `ed158e6fbd2170cfd29af0dfc38cb0f9be0a23159a61914c9c49e0cd34342f71`.
- LLVM SDK build: `fba1b05a7bd8bdc73080edd02f672cef44648267`, LLVM 23.1.1. SDK archive SHA-256: `5101e197006f166da80747b6cbb5bc05f40fdf9ac8226dd90ce8797173bbea1f`.
- Ruff: `1df6db3e463ffa1b587dcf47f25360d40389b0f7`.
- uv: `46b84fd0bfec23b72f29e8e2185ba68a65052f48`.
- Runtime corpus: CPython v3.12.7, `0b05ead877f909b7efe712db758012d9dbece7ce`, `Lib/`.

## Compiler provenance and plugin controls

The screening and paired performance runs use the same shipping PGO/BOLT compiler executable. Both plugin variants restore Ohm's early prelink MergeFunctions callback, which rustc suppresses when any LLVM plugin is loaded. The candidate additionally registers the full-LTO callback. This mechanism is restricted to the uninstrumented optimized profiles being measured; it is not a general replacement for the compiler's option guards.

Build `early-merge-plugin.cpp` as a shared library with `clang++ -O2 -shared -fPIC` and the matching SDK's `llvm-config --cxxflags`. The baseline has no additional defines; the candidate adds `-DOHM_EARLY_FULL_LTO_MERGE`. A screened alternative adds `-DOHM_PRUNE_BEFORE_MERGE` to insert GlobalDCE before merging. The separate analysis-retention screen uses the baseline plugin and `-Cllvm-args=-eagerly-invalidate-analyses=false`.

The baseline plugin and shipping compiler produced byte-identical smoke binaries and a byte-identical real Ruff executable. The initial `-Zprint-llvm-passes` stderr comparison covered only the legacy machine-pass listing; it did not establish full optimization-pipeline equality. The corrected compiler test uses `-Zautodiff=PrintPasses` without `Enable` to print the new-pass-manager pipeline, asserts it is nonempty, and checks that expected baseline `mergefunc` passes are present. Real Ruff flag/plugin binary parity and the complete final fat-LTO pipeline are checked in the same rebuilt compiler. Parallel prelink diagnostic printers interleave within lines; their full stdout is retained but is not claimed to match or normalized into a purported match. A separate unprofiled flag-off/on pair on the same compiler, transferred with its matching standard library to `charlie-serc-4`, supplies contextual timing; it is not pooled with the shipping PGO/BOLT compiler measurements.

## Concrete setup and commands

Use an isolated x86-64 Linux host with Python 3, Git, Clang C++, and the workload native build prerequisites. Keep one benchmark process per host. Use fresh task-owned targets and evidence paths; the measured harness refuses to overwrite receipts. The fixed paths below are intentional and match the recorded commands.

Place the pinned source checkouts at `/tmp/ohm-release-campaign/llvm/{ruff,uv,cpython}` and verify their `git rev-parse HEAD` values against the pins above. For example, a fresh uv checkout can be made with:

```sh
root=/tmp/ohm-release-campaign/llvm
mkdir -p "$root/uv"
git -C "$root/uv" init
git -C "$root/uv" fetch --depth 1 https://github.com/astral-sh/uv.git 46b84fd0bfec23b72f29e8e2185ba68a65052f48
git -C "$root/uv" checkout --detach FETCH_HEAD
```

Install the hash-verified shipping archive into `$root/toolchain` using the archive's `rust-1.99.0-dev-x86_64-unknown-linux-gnu/install.sh --prefix "$root/toolchain" --disable-ldconfig --without=rust-docs`. The release URL is `https://labs.astral.sh/ohm/releases/ohm-1.99.0-1/ohm-1.99.0-1-x86_64-unknown-linux-gnu.tar.gz`. This does not change a rustup alias.

Extract the hash-verified SDK from `https://rust-lang-ci2.s3.amazonaws.com/rustc-builds/fba1b05a7bd8bdc73080edd02f672cef44648267/rust-dev-beta-x86_64-unknown-linux-gnu.tar.xz` into `$root/llvm-sdk` after `mkdir -p "$root/llvm-sdk"`, using `tar -xJf SDK_ARCHIVE -C "$root/llvm-sdk" --strip-components=2`.

Run `bash setup-harness.sh` **from this evidence directory**. It copies the frozen `measure.py` bytes to the required `$root/harness/measure-v3.py`, stages the Python drivers, builds `plugins/{baseline,merge,prune-merge}.so`, and writes the fixed uv scope record (`edit_pairs=2`, `cold_pairs=1`). The source aliases are therefore explicit; no timed harness is rewritten.

Warm public registry downloads before timing:

```sh
for workload in ruff uv; do
  (cd "$root/$workload" && CARGO_HOME=/tmp/codex-cargo-home RUSTC="$root/toolchain/bin/rustc" "$root/toolchain/bin/cargo" fetch --locked)
done
```

On each workload's assigned host, run these phases sequentially:

```sh
bash run-harness.sh ruff screen   # saves original, unedited runtime executables
bash run-harness.sh ruff paired   # four real edit pairs
bash run-harness.sh ruff cold     # three empty-target pairs
bash run-harness.sh ruff runtime  # twenty-four paired lint and formatter checks
```

Substitute `uv` for `ruff` to run two edit pairs, one cold pair, and the pinned resolution workloads. The uv runtime phase first warms its isolated public PyPI cache, then runs the final suite offline. The wrapper clears inherited overrides and uses the same explicit compiler, cache, and target layout as the measurements. Its screening phase prepares executables; cold and edit results must be assessed separately from those setup runs.

## Reproducing the compiler implementation

Check out compiler commit `cad61f53e225594b8a8205b809e1e3f5a2f68d58`, based on `348339ddae4288ebb3af97d204b19479fef8f5f2`. Build stage1 compiler and `library/std` with the `bootstrap.toml` configuration recorded in `ruff.json`, using the pinned downloaded CI LLVM. Run both `tests/run-make/early-lto-merge-functions` suites with that stage1. The core test passed in this campaign; the profiler suite was capability-skipped because this stage1 did not contain the profiler runtime. The compiler build used optimization without PGO/BOLT, which is why its timing is only a separate contextual comparison.

Expose that complete stage1 sysroot at `$root/stage1`; it must include its matching standard library. The shipping standard library was rejected with E0514, and no metadata compatibility check was bypassed. After the setup and registry-prefetch steps above, `bash validate-implementation.sh` compiles real Ruff with the actual flag and plugin, checks identical executables and the complete final fat-LTO pipeline, then runs one fresh actual flag-off/on entry-edit pair. Printed-pipeline builds are excluded from performance comparisons. `actual-flag-pair.py` restores the source in a `finally` block.

In the campaign, parity ran on `charlie-oss`. Unrelated compilation then caused the contextual pair to refuse preflight before writing any timing; the compiler, matching standard library, and saved Ruff runtime binaries were transferred intact to `charlie-serc-4` for the pair and final runtime checks. `ruff-validation.json` records this separate host cohort; its hashes must match `ruff.json` before combining their conclusions. Timings are not pooled across hosts.

## Build measurement

Use isolated pinned worktrees and absolute shipping Cargo/rustc paths. Keep public registry downloads warm and build offline. Unset concurrency overrides, incremental overrides, Rust flags, shared build directories, wrappers, and trust opt-ins. Cargo's default CPU concurrency is retained. The OS page cache is not flushed between runs; target-cold refers to compiled Cargo artifacts. `measure.py` captures elapsed time, child CPU time, peak child RSS, compiler contention, all-process CPU activity, iowait/steal, exact command/environment allowlist, and output hashes. Every root rebuild must log an actual package compilation.

- `paired-ruff.py` runs four alternating baseline/candidate and candidate/baseline pairs. Each pair changes an error-message literal in Ruff's entrypoint to a new pair-specific value. Both variants see exactly the same edited source hash. The original source is restored in a `finally` block.
- `paired-uv.py` uses an equivalent entrypoint refactor that materializes the argument iterator in a uniquely named local binding for each pair. Both variants see exactly the same source. The original source is restored afterward. The uv scope was fixed at two edit pairs and one cold pair before the edit pairs completed, regardless of their direction; its smaller sample is inconclusive for a uv speedup.
- `cold-pairs.py` runs three counterbalanced Ruff pairs and one uv pair, according to the recorded scope decision, with a newly empty task-owned target directory before every command. It checks that more than 150 packages compile, keeps raw receipts outside the target, and records final binary hashes and sizes. It reuses one bounded target location to avoid path and storage differences.

The runtime inputs are the original, unedited screening binaries. The first attempted repeated Ruff baseline was a 0.289-second Ohm artifact restoration; no compiler ran. That sample is retained and explicitly rejected. Source edits and compilation assertions prevent this from entering the final rebuild pairs.

## Runtime checks

Ruff runs uncached isolated lint and format checks over the pinned CPython `Lib/` directory. Lint uses `--exit-zero`; the formatter encounters intentional invalid-syntax fixtures and returns 2 consistently. Full stdout, stderr, exit codes, and hashes are retained. Lint stdout and formatter stdout must be byte-identical. Exactly two known lint warnings may appear in either order; every warning line is retained and validated. Formatter stderr must be empty.

uv resolves the pinned repository's `test/requirements/trio.in` and `jupyter.in`, using a single warmed isolated public PyPI cache, Python 3.12 markers, and `--exclude-newer 2026-10-01T00:00:00Z`. Each timed run is offline and removes the output file first. `--no-header` omits the command-path header. Requirement output must be byte-identical, with no stderr normalization except the reported resolution duration.

Initial screening runtime rounds use six repetitions per variant. The selected baseline and candidate receive 24 additional counterbalanced runtime pairs after compilation stops. Ruff final runtime checks run on `charlie-serc-4`, a separate cohort from the shipping build timings on `charlie-oss`, after unrelated jobs began on the original host. Exact compiler, standard-library, and runtime executable hashes are retained across the transfer. The new host must pass a 30-second >=95% idle and >=20 GiB free-space gate. Report these checks as sampled runtime guardrails, not proof that every workload is unaffected.

## Interpretation

Root rebuild, target-cold build, instrumented pass profile, memory, executable size, and runtime data are separate measurements. A large pass-profile share does not establish a comparable uninstrumented speedup. Single-run screens select hypotheses; the repeated pairs support any final speed claim. Record failed hypotheses and rejected runs alongside the accepted data.
