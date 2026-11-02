# Ruff instruction counts for Ohm Rust #326

Six independent Linux workers compiled the Ruff edit that adds an example and glob reference to the `lint.per-file-ignores` option. On each worker, Cargo and its children retired 11.39% to 11.47% fewer userspace instructions with the new LLVM register coalescer. The median paired reduction was **11.42%**, or **11.38%** when the next unchanged build was included. Three workers ran the parent first and three ran the candidate first. The six paired differences give an exact two-sided sign-test p-value of 0.03125. [Compiler change](https://github.com/astral-experiments/ohm-rust/pull/326) · [Ruff edit](https://github.com/astral-sh/ruff/pull/28106)

| Edited command | Workers | Parent instructions, median | Candidate instructions, median | Paired reductions |
| --- | ---: | ---: | ---: | --- |
| `cargo build -p ruff_workspace --lib` | 6 | 133.060 billion | 117.866 billion | 11.47%, 11.43%, 11.39%, 11.42%, 11.42%, 11.39% |
| `cargo test -p ty_server --test e2e --no-run` | 2 | 31.965 billion | 31.975 billion | −0.109%, +0.046% |

Only `ruff_workspace` rebuilt on the edited library build, and every artifact was fresh on the next build. Both arms emitted `E0308` for the invalid edit. The edited and repaired native option clients had the same SHA-256 as the independently clean client on all six workers, and the old client differed. The `ty_server` control used a separate real edit. Its edited, repaired and clean executables were byte-identical, exposed the same 152 test names, and passed the added test. The deliberately failing test produced a different executable. The counter stopped before test execution. [Test edit](https://github.com/astral-sh/ruff/pull/27836)

`registration.json` records the workload, required sample, primary metric, and admission rule. `runs.json` identifies all eight GitHub artifacts by run, size, and SHA-256. It also records the initial eight dispatches that stopped at a branch-name check before compilation. Both batches are visible in the run history. The measured factory built the two compilers on the same worker against the same binary LLVM SDK. A later factory independently rebuilt the draft's `74d8eeab285e` source and reproduced all 65 installed files in each arm byte-for-byte, including file modes. [Measured factory](https://github.com/astral-experiments/ohm/actions/runs/41391043311) · [Rebuild](https://github.com/astral-experiments/ohm/actions/runs/41397879204)

The follow-up at `1589b5884e0a` clears inherited coalescer sources before bootstrap configures Cargo. Its independent physical rebuild also reproduced all 65 installed files in each measured compiler. We compared each path, archive and installed mode, size, and SHA-256 from the installed bytes. Four child-process controls exercised authenticated and rejected sources with the real Cargo build script. The portable reproducer covers 16 separate source and patch fallback cases. [Compiler comparison](rebuild.json) · [Follow-up compiler rebuild](https://github.com/astral-experiments/ohm/actions/runs/41400188530) · [Bootstrap reproducer](../bootstrap-repro/README.md)

From an authenticated checkout of this branch, run the following with Python 3.11 or newer and a current GitHub CLI. The reader downloads the eight original artifacts, verifies their SHA-256 hashes and worker identities, then reopens their raw instruction counters, Cargo output, native option-client results, and test inventories.

```sh
python3 -IB scripts/ruff-workspace-remat/results/read_instructions.py
```

To verify archived downloads offline, pass `--archives DIR` with files named `RUN-ARTIFACT.zip` as listed in `runs.json`. To collect another independent pair, run the following from an Ohm checkout and reverse `pair_order` for the opposite order.

```sh
gh-auto workflow run ci.yml -R astral-experiments/ohm \
  --ref charlie/qa-ruff-coalescer-physical-20261102 \
  -f reviewed_head=9d90d41466d47d6b2e2b45389d2082aa09ac4098 \
  -f compiler_mode=matched -f suite=build -f pair_order=normal,defer
```
