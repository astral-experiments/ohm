# Ruff PEP 723 test-build instructions on x86-64 Linux musl

Ruff added four tests when it improved error spans in script metadata. Each paired host switched between the two original Ruff commits, including their respective lockfiles. The two whole Cargo commands built the edited test executable and then immediately requested it again. All test execution was outside the instruction counters. [Ruff change](https://github.com/astral-sh/ruff/commit/672bb4edf04c84f8b0753346359daee4057158f2) · [Registered confirmation plan](../PLAN.md)

| Whole Cargo command | Parent instructions | This PR | First 12 pairs | Next 12 pairs |
| --- | ---: | ---: | ---: | ---: |
| Build the real edit | 16.841B | 11.931B | 1.412× (1.410–1.413) | 1.411× (1.410–1.412) |
| First unchanged test build | 10.277B | 0.582B | 17.662× (17.660–17.664) | 17.661× (17.658–17.663) |
| Edit plus first unchanged | 27.118B | 12.513B | 2.168× (2.165–2.168) | 2.167× (2.165–2.168) |

The individual instruction columns are medians from the first cohort. Both ratio columns show the median of paired parent/candidate instruction counts and its two-sided 96.14% interval. Each cohort used twelve freshly booted workers in six opposing-order blocks. The bounds are the third and tenth sorted ratios. For the repeat, all twelve ratios exceeded two in each cohort (one-sided sign probability 1/4,096). For the combined endpoint, 12/12 and 12/12 exceeded two (one-sided sign probabilities 1/4096 and 1/4096).

## Native results and disk use

The parent compiled `compact_str`, `zmij` and `ruff_python_ast` on both commands. The candidate compiled the root test on the edit and performed a link-only rustc invocation on the repeat. The traced copies of all four commands called the target GNU linker once. Each old executable passed 49 tests and each corrected executable passed 53. The deliberately wrong delimiter edit failed its one expected assertion. The ill-typed edit produced E0308 and the repair matched a clean build byte for byte. Every comparison required the full native ELF. [Source and compatibility tests](https://github.com/astral-experiments/ohm/actions/runs/41173218253) · [Unscored test builds](https://github.com/astral-experiments/ohm/actions/runs/41174368146)

After counting hardlinks once across target and build directories, median candidate-minus-parent allocated bytes were -1,069,056 and -1,069,056 after edit and repeat. Independently empty edited builds differed by +0 and +0 bytes. The patched compiler driver grew by 5,752 bytes. The per-worker ledgers check the six native payload categories, normalized filenames and duplicate contents.

The compiler sources were `adea62b64bb86ad18946457dfb59f36b2d8fcab4` and `d52336754e01c65758f0be7335b191be47baf02f`. Both used Cargo `c18e91b514b2c4e4966c9ab03232c804af3e1b57` and the same 182 other SDK files. The original source checks and 188 native-provider cases cover both older Cargo readers and the compatible reader. [Compiler-source job](https://github.com/astral-experiments/ohm/actions/runs/41170783373) · [Native-provider jobs](https://github.com/astral-experiments/ohm/actions/runs/41173218253)

The separate `cargo build -p ruff_python_ast --lib` experiment stopped when one unmodified parent produced different `.rmeta` bytes between warm and clean builds. Its workers and counters contributed no data here. [Closed library screen](https://github.com/astral-experiments/ohm/actions/runs/41178973081)

## Replay

From the evidence checkout, run the following standard-library-only Python 3.11+ command.

```sh
python3 -IB scripts/ohm-musl-pep723-test-hardware/confirmation/evidence/replay.py
```

The offline replay checks the retained original clock events, 28 hardware inheritance calibrations per host, all 36 typed Cargo units, complete test inventories, the expected assertion and span, and inode-level disk use. It recomputes all three estimates and intervals. The complete official ZIPs also include the three native ELF images, raw per-thread linker traces, independent clean starts and repairs. While the GitHub artifacts are available, run the original verifier at each enrolled checkout.

```sh
raw=$(mktemp -d)
evidence=$PWD/scripts/ohm-musl-pep723-test-hardware/confirmation/evidence
for phase in primary independent; do
    python3 -IB "$evidence/originals.py" "$phase" "$raw"
    sha=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["head"])' "$evidence/$phase/report.json")
    git worktree add --detach "$raw/$phase-source" "$sha"
    python3 -IB "$raw/$phase-source/scripts/ohm-musl-pep723-test-hardware/confirmation/read.py" \
        "$raw/$phase" "$raw/structural.zip" > "$raw/$phase-readback.json"
    cmp "$raw/$phase-readback.json" "$evidence/$phase/report.json"
done
```

The ordinary command counted on each host was `cargo +ohm test --locked --offline -p ruff_python_ast --lib --no-run --target x86_64-unknown-linux-musl -j4 --message-format=json`. The original workers build the parent of the Ruff edit from empty target and build directories, switch to the edit, then run that command twice. The matched source-built compilers and Cargo #301 are required. [Hardware setup and gates](../../PLAN.md)

## Primary paired hosts

[Official run](https://github.com/astral-experiments/ohm/actions/runs/41180059350) · [Original ZIP identities](primary/originals.json) · [Raw counts and digest for each pair](primary/report.json)

| Block | Order | Edit P/C | Repeat P/C | Combined P/C |
| ---: | :---: | ---: | ---: | ---: |
| 1 | PC | 1.41262 | 17.66385 | 2.16825 |
| 1 | CP | 1.40870 | 17.66343 | 2.16273 |
| 2 | PC | 1.41197 | 17.65995 | 2.16783 |
| 2 | CP | 1.40972 | 17.66896 | 2.16487 |
| 3 | PC | 1.41179 | 17.66407 | 2.16695 |
| 3 | CP | 1.41018 | 17.65999 | 2.16523 |
| 4 | PC | 1.40982 | 17.66365 | 2.16561 |
| 4 | CP | 1.41222 | 17.66123 | 2.16815 |
| 5 | PC | 1.41269 | 17.65912 | 2.16937 |
| 5 | CP | 1.41252 | 17.65531 | 2.16788 |
| 6 | PC | 1.41148 | 17.66551 | 2.16806 |
| 6 | CP | 1.41305 | 17.65957 | 2.16884 |

## Independent paired hosts

[Official run](https://github.com/astral-experiments/ohm/actions/runs/41181013450) · [Original ZIP identities](independent/originals.json) · [Raw counts and digest for each pair](independent/report.json)

| Block | Order | Edit P/C | Repeat P/C | Combined P/C |
| ---: | :---: | ---: | ---: | ---: |
| 1 | PC | 1.41089 | 17.65470 | 2.16529 |
| 1 | CP | 1.41218 | 17.65950 | 2.16769 |
| 2 | PC | 1.40989 | 17.65954 | 2.16552 |
| 2 | CP | 1.41510 | 17.65811 | 2.17142 |
| 3 | PC | 1.40814 | 17.66327 | 2.16317 |
| 3 | CP | 1.41311 | 17.66665 | 2.17041 |
| 4 | PC | 1.41066 | 17.65792 | 2.16613 |
| 4 | CP | 1.40845 | 17.66318 | 2.16341 |
| 5 | PC | 1.41214 | 17.66203 | 2.16803 |
| 5 | CP | 1.40993 | 17.66498 | 2.16481 |
| 6 | PC | 1.41131 | 17.66117 | 2.16715 |
| 6 | CP | 1.41162 | 17.65991 | 2.16754 |
