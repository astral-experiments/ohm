# Fewer repeated byte-string hashes in the Ruff typeshed check

After Ruff updated its vendored typeshed, ordinary `cargo +ohm check -p ty_vendored --lib --locked --offline -j4` retired **8.2700% fewer user instructions**. Its one edited compiler retired **32.5146% fewer**. Six independent, counterbalanced pairs put the median reductions in 8.2498–8.2817% and 32.5096–32.5149%, respectively (distribution-free 96.875% intervals, exact two-sided sign *p* = 0.03125). This measures the named crate. [Original Ruff edit](https://github.com/astral-sh/ruff/pull/29042)

| Slot | Order | Parent Cargo | Candidate Cargo | Parent rustc | Candidate rustc | Original |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 0 | PC | 675,282,189 | 619,471,367 | 171,418,204 | 115,690,901 | [Run 41605149392](https://github.com/astral-experiments/ohm/actions/runs/41605149392) |
| 1 | CP | 675,409,110 | 619,517,252 | 171,422,510 | 115,685,225 | [Run 41605154645](https://github.com/astral-experiments/ohm/actions/runs/41605154645) |
| 2 | PC | 675,184,937 | 619,444,746 | 171,418,895 | 115,682,542 | [Run 41605160162](https://github.com/astral-experiments/ohm/actions/runs/41605160162) |
| 3 | CP | 675,383,223 | 619,450,026 | 171,420,057 | 115,682,935 | [Run 41605165765](https://github.com/astral-experiments/ohm/actions/runs/41605165765) |
| 4 | PC | 675,048,590 | 619,358,378 | 171,420,020 | 115,683,258 | [Run 41605171418](https://github.com/astral-experiments/ohm/actions/runs/41605171418) |
| 5 | CP | 675,143,566 | 619,265,536 | 171,419,313 | 115,683,388 | [Run 41605178214](https://github.com/astral-experiments/ohm/actions/runs/41605178214) |

## Controls and costs

* One ordinary build-script process generated the complete new ZIP, followed by one ty_vendored compiler. Both old and new untouched checks scheduled zero compilers and zero generators. The extra whole-command measurement, using one traced inheriting event, reproduced an 8.2598% median reduction. The original ordinary Cargo ran under one unscaled inheriting user-instruction event without any rustc wrapper or trace. The individual compiler meter starts at successful exec and includes all subsequent threads and descendants.
* A separate P/C/P comparison kept the exact parent rustc argv, source, ZIP, all three direct upstream metadata files, search paths and credential-free compiler environment. It reduced physical rustc instructions by 26.5912% (26.3990–26.6854%). The new mode that removed just the incremental option saved 10.6484% (10.5032–10.9043%). The independently emitted outputs in these controls contain the same full 5,576,596-byte ZIP. Each 5,586,893-byte incremental .rmeta has the same bytes outside the typed 16-byte private crate hash, including the public and global hashes, all item rows and all required upstream hashes. All 12 positive controls across the two modes passed the same typed comparisons. [Metadata readback](same-input-metadata.json)
* Every ordinary edited check and independent package clean produced identical complete metadata under identical upstream inputs. Fully empty workspace histories can produce different upstream ruff_db hashes. The originals, all three direct provider inputs and changed required metadata rows are kept for each such comparison. Both matched SDKs compiled an actual Rust consumer of Ruff's vendored filesystem. All six hosts produced the identical old and new executable digests registered in the pilot. The old reader found neither of the new typing docstrings; the edited/independently clean reader found both and reported the new upstream source commit. The genuine E0308 and repair tests also passed, and all 819 ZIP entries matched their expected source bytes in every history.
* The whole cold ty_vendored check used 0.0150% more instructions (0.0107–0.0222%). The whole cold ruff_python_parser check used 0.0355% more (0.0244–0.0402%). The isolated parser compiler ranged from 0.0187% more to 0.0382% fewer (median 0.0246% fewer). The subsequent unchanged whole Cargo check ranged from 0.0190% more to 0.0362% fewer.
* The interner stores 16 additional bytes per distinct byte sequence of at least 64 KiB; ordinary smaller entries have the same size. The typed allocation record still fits in the former record size, including on ARMv7. This study measured retired instructions and emitted bytes. Process peak RSS is an open measurement. The incremental cache version changes because the fingerprint composition changes. [Matched compiler factory and Rust tests](https://github.com/astral-experiments/ohm/actions/runs/41595501573)

## Reopen or remeasure

From the packaging checkout, recompute every endpoint from permanently retained raw hardware records:

```sh
python3 -IB scripts/ruff-frozen-literal/evidence/verify.py
```

The independent verifier authenticates every complete original Actions ZIP against GitHub, requires six independent boot and runner identities, then reopens original native products and kernel records. Run it while the hosted binaries are retained:

```sh
python3 -IB scripts/ruff-frozen-literal/aggregate.py \
  scripts/ruff-frozen-literal/evidence/confirmation-runs.json /tmp/ohm-literal-six-originals
```

To repeat the ordinary study on a new runner, dispatch the QA branch (choose rank 0–5). The checked-in factory registration fixes the two Rust commits, original Cargo, LLVM and standard library. Repeat each of the six predeclared ranks for a fresh independent confirmation.

```sh
qa_branch=charlie/qa-frozen-literal-ruff-29042-20261103
qa_head=$(gh-auto api "repos/astral-experiments/ohm/git/ref/heads/$qa_branch" --jq .object.sha)
gh-auto workflow run ci.yml -R astral-experiments/ohm --ref "$qa_branch" \
  -f reviewed_head="$qa_head" -f rank=0
```

All 220,167,245 original bytes were authenticated before price comparison. Each archive is identified by full SHA-256 and artifact ID. The 415 response from using an inappropriate media type when downloading the first archive contained no benchmark data. The reader used the Actions API's default response to fetch the originally enrolled bytes. [Predeclared six run IDs](confirmation-runs.json) · [Raw clock records](kernel-clocks.json) · [Run, boot and artifact custody](originals.json) · [All per-rank data](six-pair-results.json)
