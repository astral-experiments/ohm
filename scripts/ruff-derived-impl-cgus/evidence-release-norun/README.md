# Ruff package test builds after the #28392 commit switch

Six independent Linux boots reproduced a **22.90% reduction in retired user instructions** for the first ordinary `cargo +ohm test --no-run -p ruff` after switching between the two real Ruff revisions. The paired median's exact 96.875% interval is **22.87–22.93%**, with six favorable outcomes and an exact two-sided sign p of 0.03125. Each boot ran both compilers on the same machine, three parent-first and three candidate-first. A separate parent-first pilot saved 22.91% and is excluded from the six. [Prospective registration](../norun/six-plan.json) · [Confirmation workers](https://github.com/astral-experiments/ohm/actions/runs/41758087313) · [Original pilot](https://github.com/astral-experiments/ohm/actions/runs/41756383381)

The Rust pair was the published Ohm −24 source parent `f5a51d8cc3e76236c2d0f17d495d59ebb03306e4` and the isolated receiver-partition candidate `025c787a77f5d887ba9bf860ef69b7756b59fe57`. Each compiler used the same stage-2, native-PGO, ThinLTO and BOLT release recipe. Cargo and Wild came from the same signed −24 installation. Each worker had a fresh target and reused the same absolute paths between arms. Cargo ran offline with four jobs and 505 authenticated locked registry archives. These measurements isolate the change that became Rust #354 on its historical base. [Parent factory](https://github.com/astral-experiments/ohm/actions/runs/41737296261) · [Candidate factory](https://github.com/astral-experiments/ohm/actions/runs/41738530557)

The Ruff source switched from `f3280423f6c535690287e8169c25929f8d6433ce` to `d136bd8d002a648de5f344df602e492658306f1e`. The change corrects the example from `lint.line-length = 100` to `line-length = 100` in the CLI argument definition and docs. Ruff's build script watches Git HEAD and emits the commit hash. The run changed the HEAD and compiled that new hash into the executable. A working-tree edit at a fixed HEAD is a separate workflow. [Ruff change](https://github.com/astral-sh/ruff/pull/28392) · [Ruff build script](https://github.com/astral-sh/ruff/blob/d136bd8d002a648de5f344df602e492658306f1e/crates/ruff/build.rs)

| Retired user instructions | Parent median | Candidate median | Median paired reduction |
|---|---:|---:|---:|
| First ordinary edited test build | 30.069B | 23.183B | **22.90%** |
| Separately initialized, observed edit | 30.070B | 23.184B | 22.89% |
| Normal Ruff library rustc in the observed edit | 13.806B | 6.908B | **49.96%** |
| Separate Ruff library test-harness rustc | 1.675B | 1.673B | 0.11% |
| Cold original | 2.187T | 2.179T | 0.34% |
| Independently empty edited build | 2.187T | 2.179T | 0.34% |
| Unchanged original | 0.507B | 0.507B | −0.017% |
| Unchanged edited | 0.507B | 0.507B | −0.019% |

Every primary measurement counted the entire Cargo command and its descendants. The separate observed replay tied real argv, executable identities and lifetime hardware events to ten Rust compiler invocations and nine signed linker launches in each arm. Both unchanged replays ran zero rustcs and zero linkers. Both compilers regenerated four normal-library codegen objects. The parent retained 232/236 and emitted 2,289,552 bytes, compared with 237/241 and 1,114,224 bytes for the candidate. Both retained all 148 native objects for the distinct library test harness. Edited on-disk allocation had a paired median reduction of 137,216 bytes on approximately 3.27 GB. [All six pairs and original counts](paired.json)

An optional sum over every thread and fork failed to close against its independently recorded whole-command event on two of the twelve observed edit arms, by 702,893,540 instructions on slot 2 parent and 2,699,167,614 on slot 5 candidate. Their raw decompositions are explicitly refused. The six-pair linker instruction total is withheld. The ordinary inherited counter, the direct process-lifetime counters and the physical nine-launch roster use separate measurements. The original strict refusal can be reproduced with `--strict-checkpoint-sum`. [Independent reader](reopen_norun.py)

Each role and boot checked all eight complete native test executables and the CLI against repaired and independently empty edited builds. The 396 distinct registered test cases across the eight targets retained their per-target inventories. Three real tests, changed CLI help, valid and invalid configuration, and lint behavior ran after instruction counting. An invalid Rust body produced E0308 twice. The reader reopened 22 original executable bodies per boot and independently ran the old and new programs. [Raw archive and native SHA ledger](originals.json) · [Compact control archive manifest](controls.json)

## Reproduce

From a read-authorized Ohm packaging checkout, a fresh historical Ruff worktree at the exact NEW source, and an isolated signed −24 Cargo home, replay the completed six workers with the following command. The default reader uses at most one full archive and one materialized native executable at a time for local verification. Downloaded originals are retained at the supplied location. Set `RUSTUP_HOME` to the admitted −24 Rustup installation.

```sh
e=scripts/ruff-derived-impl-cgus/evidence-release-norun
python3 -IB "$e/fleet.py" --root /tmp/ohm-ruff-norun-originals \
  --reader "$PWD/$e/reopen_norun.py" --ruff /absolute/path/to/ruff-at-d136bd8 \
  --run 41758087313 --head e5a7aa227e9068e3de44b1e031e940ad6d8b65ec
```

To run new hardware pairs from the same registration, dispatch the following nonrelease workflow. The reviewed head and SDK transports are pinned.

```sh
gh-auto workflow run ci.yml -R astral-experiments/ohm \
  --ref charlie/qa-ruff-cli-help-norun-six-stage2-20261104 \
  -f reviewed_head=e5a7aa227e9068e3de44b1e031e940ad6d8b65ec
```

The compact archive stores all 7,027 original control members from the separate pilot and six boots, including original raw hardware events, kernel exec argv, native behavior output and independently reopened receipts. Each original ZIP's complete length, SHA and deduplicated native members are separately committed. The full compressed executable bodies are in the authenticated hosted originals.
