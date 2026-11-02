# Where the Ruff #25492 edited build spent its instructions

The real CRLF edit took **61,066,244,767 retired user instructions** in the ordinary Ruff CLI build. A second boot reproduced all 27 rustc invocations and both Wild links. It recorded **23,344 instruction samples** at a period of 2,500,003, covering 95.72% of the independently counted 60,969,897,935 instructions in that build. The ordinary counter includes the Cargo process and its descendants. Per-function and per-owner estimates come from the second boot. [Ordinary command, source and native controls](ORDINARY.md) · [Recorded sample counts and owner tables](profile.json)

## What the compilers delivered

All 52 complete output files differed between OLD and edited NEW. They comprise 25 rlibs, their 25 rmeta files, the `ruff_macros` proc-macro library and the CLI. Each also differed between edited NEW and independent empty NEW, despite matching typed CRLF verdicts, CLI cases and native rlib objects. A full rmeta or ELF digest change alone therefore cannot establish a semantic change. No consumer in this packet could be skipped on exact complete-output equality.

All **3,096** named native object payloads in the 25 edited rlibs matched their independent empty NEW objects. Eleven differed from OLD. The changes were in `ruff` (3), `ruff_db` (2), `ruff_linter` (1), `ruff_notebook` (1), `ruff_server` (1) and the two `ruff_source_file` feature configurations (2 and 1). All native payloads in the other 18 rlibs stayed unchanged. Per-archive object names use the registered normalization of rustc's random seven-character invocation suffix. Full SHA-256 compares content. All 25 embedded `lib.rmeta` payloads changed between OLD and edited NEW and between edited NEW and empty NEW.

The trace reached 118 distinct consumer/input rows within these 27 units. All named complete files with changed bytes. For example, `ruff_python_ast` took `libruff_source_file-4d18d41a9d82da5a.rmeta`. `ruff_linter` took that file and `libruff_python_ast-5a2d1a22d0fcf0c1.rmeta`. `ruff_workspace` then took `libruff_linter-1ebfba3e634b8a34.rmeta`. The final CLI was also given their rlibs. The trace records which files were supplied. A query's reads inside those files are unobserved. The typed executable independently required the new line-end result on both feature configurations. [Observed arguments and per-archive results](profile.json)

## Instruction budget

Each sample appears once in the table, assigned to the deepest recognized phase on its DWARF stack. Estimated instructions are the count times the hardware period. The 21.0% uncategorized share is retained. Several inclusive stack categories can describe one sample, so the receipt gives their any-frame counts separately from exclusive-leaf counts. [Raw classifications](profile.json)

| Deepest recognized work | Samples | Share of samples | Estimated billion instructions |
| --- | ---: | ---: | ---: |
| Semantic front-end work | 5,268 | 22.6% | 13.17 |
| Unclassified | 4,903 | 21.0% | 12.26 |
| Other query and dependency graph operations | 3,535 | 15.1% | 8.84 |
| Metadata encode and public API hash | 2,124 | 9.1% | 5.31 |
| Native code generation | 1,709 | 7.3% | 4.27 |
| Query green validation or forcing | 1,577 | 6.8% | 3.94 |
| Two Wild process trees | 1,493 | 6.4% | 3.73 |
| Incremental graph and persistence | 1,345 | 5.8% | 3.36 |
| Metadata decode | 1,024 | 4.4% | 2.56 |
| Monomorphization collection | 350 | 1.5% | 0.88 |
| Archive assembly, external rustc children and link preparation | 16 | 0.07% | 0.04 |

`DepGraphData::try_mark_previous_green` accounts for 1,567 exclusive leaf samples. Every stack touching any recognized green-validation or force entry accounts for 2,675 samples, or 6.69B estimated instructions. The 4 KiB unwind can omit deeper frames, so this is an observed budget rather than an upper bound on unobserved callers. Eliminating all such sampled work would still be far short of the **30.533B** ordinary-instruction saving required for 2×. Of `ruff_linter`'s 9,387 samples, 641 land in that one function and 2,212 in the broad front-end category. Its frequent front-end entries span proc-macro bridge dispatch, name resolution, AST lowering and stable hashing. Most Wild leaf IPs lacked symbols, while its physical process ownership was independently recorded. [Earlier targeted green-validation PR](https://github.com/astral-experiments/ohm-rust/pull/265)

`ruff_python_ast` spends 382 of 1,887 samples (20.2%) in all metadata encoding and public API hashing combined. Whole-workflow leaves include `EncodeContext::encode_span`, `EncodeContext::encode_def_ids`, `ReachabilityGraphBuilder::build_graph` and `build_public_hashes`. Existing Ohm work covers the public-graph representation, and #261 already tested this Ruff edit. The smaller `ruff_markdown` process had 42 of 110 samples in metadata decoding, and `ruff_server` had 538 of 2,066 in native code generation. These observations price broad subsystems. The packet does not identify an operation that could remove 20% of a compiler or halve the whole build. [Compact public-graph IDs](https://github.com/astral-experiments/ohm-rust/pull/194) · [Reachability graph on the same edit](https://github.com/astral-experiments/ohm-rust/pull/261) · [Incremental query writeback](https://github.com/astral-experiments/ohm-rust/pull/203) · [Incremental graph storage](https://github.com/astral-experiments/ohm-rust/pull/325)

## Reproduction and retained decisions

Both workers used the original proposal #253 GNU/Linux SDK and the genuine Ruff revisions. The sampler used the same verified registry of 488 packages, source pair and arguments, restored the literal child environment, and disabled perf's build-ID caching. Every actual compiler and linker argument and environment passed on each of the four visits. Cargo's full unit sets, dirty results, 644 previously registered native objects and their donor status, both typed witnesses and the CLI outcomes also matched. The raw files contain each sampled leaf's PID and IP, the DWARF frame stacks independently joined by PID and instruction address and the original perf data. [Preregistered measurement and comparison rules](DIAGNOSTIC.md)

The sampler producer ended in failure on a redundant summary that compared the randomized locked-autocfg UUID verbatim across boots. The original artifact was retained. The independent reader authenticated both full ZIP sizes and digests, verified every member CRC and rechecked all actual argument, environment, artifact, clock and sample gates. Only the cold OLD and empty NEW summaries required the already registered autocfg normalization. The edited and unchanged compiler and linker rosters matched without that normalization. Seven deliberately invalid summary mutations failed. The first readback then stopped on duplicate displayed Cargo unit descriptions. The successful readback keyed each physical unit by its complete Cargo description and distinct output basenames. All results use the same two source archives. [Sampler and original verdict](https://github.com/astral-experiments/ohm/actions/runs/41466356507) · [First readback](https://github.com/astral-experiments/ohm/actions/runs/41468372017) · [Accepted independent readback](https://github.com/astral-experiments/ohm/actions/runs/41468593729) · [Rendered receipts](https://github.com/astral-experiments/ohm/actions/runs/41468878382)

While the original artifacts are retained, rerun the reader from an authenticated OSS worktree. It verifies both finished workers' immutable commits, first attempts, original terminal states, archive IDs, sizes and digests without compiling Ruff.

```sh
qa_branch=charlie/qa-ruff-line-end-25492-20261102
qa_commit=$(/home/dev-user/.local/bin/gh-auto api "repos/astral-experiments/ohm/git/ref/heads/$qa_branch" --jq .object.sha)
/home/dev-user/.local/bin/gh-auto workflow run ci.yml --repo astral-experiments/ohm --ref "$qa_branch" -f "reviewed_head=$qa_commit" -f report=false
```
