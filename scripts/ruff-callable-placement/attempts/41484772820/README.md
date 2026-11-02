# Test builds after a Ruff source line edit

A documentation edit in Ruff's `ty_python_semantic` moved code in `callable.rs` by 246 lines. Across six fresh Linux workers the median paired reduction in retired user instructions for the edited test build was **9.5192%**. The exact 96.875% sign interval for the paired median was 9.4870–9.5513%. The two-sided paired sign test gave p = 0.03125 and the preregistered one-sided comparison across all 20 balanced order assignments gave p = 0.05. The discovery pair is excluded. [Original Ruff edit](https://github.com/astral-sh/ruff/pull/28277) · [Six worker jobs](https://github.com/astral-experiments/ohm/actions/runs/41484772820) · [Protocol before the runs](https://github.com/astral-experiments/ohm/blob/f417930f23db5aa87a0fc6223f7686fe210ebff3/scripts/ruff-callable-placement/replication.json)

```sh
cargo +ohm test --no-run -p ty_server --test e2e --locked --offline -j4
```

| Worker | Order | Parent instructions | Candidate instructions | Reduction |
| ---: | --- | ---: | ---: | ---: |
| 1 | Parent first | 473,803,486,948 | 428,853,719,219 | 9.4870% |
| 2 | Candidate first | 473,950,915,780 | 428,823,675,465 | 9.5215% |
| 3 | Candidate first | 473,974,808,943 | 428,704,195,186 | 9.5513% |
| 4 | Parent first | 473,959,815,873 | 428,831,234,629 | 9.5216% |
| 5 | Parent first | 473,917,777,080 | 428,815,263,977 | 9.5169% |
| 6 | Candidate first | 473,878,365,193 | 428,800,356,599 | 9.5126% |

The two source-built compilers use the same Cargo, LLVM and Wild. The parent is Ohm Rust `531eb1980c08c75ccbf3f6b77adbee53cd9b8bd5`. The candidate is `4e546b27c311f29d99f9528e64420887f57c7538`. Instructions cover the complete Cargo process tree. Each worker started from empty build state for each arm. Native test execution, file observation and GDB ran outside the counter.

The candidate reused 63 codegen units on the forward edit and on the reverse in every worker. The parent reused zero through this path. The full objects and test executable matched independent edited builds. GDB resolved the moved source site, the 168 test names matched, and an injected failing assertion failed and passed after repair. Both arms allocated 368,848,896 bytes for native objects. The candidate's optional records occupied 7,482,727 bytes. The measured increase in total allocated target and shared state ranged from 7,454,720 to 7,569,408 bytes.

Two earlier counterbalanced workers tested a different Ruff settings edit and a separate `ty_server` edit. The settings build used 17.20% fewer instructions on both workers. The other test build used 3.48% more, and the two cold workflows used 4.50–5.69% more. The settings build missed its registered 2× criterion. The complete raw readers passed. The first aggregate reader lacked its required 15 GiB of free space. A sufficiently provisioned reader reopened the original data and reported the decision. [Raw hardware runs](https://github.com/astral-experiments/ohm/actions/runs/41485360543) · [Final two-worker decision](https://github.com/astral-experiments/ohm/actions/runs/41492659316)

The six `block-*.json` files bind the original archive digests, independent reader, PMU counts and worker boot IDs. The six `observations-*.tar.gz` files retain the original small instruction, process, artifact-inventory, test and debugger reports. The independent reader verifies the complete native-object witnesses from the original worker archives.

From this checkout on the OSS devbox, use an empty directory to repeat the full readback.

```sh
out=$(mktemp -d)
python3 -IB scripts/ruff-callable-placement/reopen_pairs.py "$out"
cat "$out/summary.json"
```

To run the six hardware blocks again on the original source registration, dispatch its frozen QA branch.

```sh
/home/dev-user/.local/bin/gh-auto workflow run ci.yml -R astral-experiments/ohm \
  --ref charlie/qa-ruff-db-link-cause-20261102 \
  -f reviewed_head=f417930f23db5aa87a0fc6223f7686fe210ebff3 \
  -f distributions=callable-confirm
```
