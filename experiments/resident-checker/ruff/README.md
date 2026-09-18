# Ruff parser test-suite compatibility

The [recorded run](../data/ruff-parser-tests.json) runs all targets and doctests for `ruff_python_parser` at Ruff revision `fd5d636bdd58a5a42e0212988e1cdf710eec8558`. Both the patched Ohm compiler with its resident query graph enabled and the same compiler with the graph disabled passed 245 unit tests, 557 syntax fixtures, one inline-test generator, and 10 doctests: 813 in each mode, with no failures, ignored tests, or filtered tests. The package has no optional features; the reproduction still requests `--all-features`.

This checks compatibility of the instrumented compiler with the unedited parser and runs Ruff's actual test executables. Cargo starts compiler processes normally; these results do not establish reuse or correct invalidation across source edits in one compiler process.

The [separate edit results](../data/ruff-parser-edits.json) record an initial resident sweep: the 912 named library functions and 1,601 named test-build functions checked clean, but the original edit APIs accepted none of the candidate sites. Fresh compilers independently verified eight edits that should fail compilation and four edits that compile but should fail a targeted Ruff runtime test.

An extended editor then changed the real `lexer::is_unicode_identifier_start` function and `StringParser::parse_octet` method. Each edit produced `E0308`, recovered, produced the error again, and recovered again in the same compiler process. Four unrelated functions and a fifth const function, `is_complex_number`, kept their type and borrow results after the dependency fix below. The resident errors agreed with fresh Ohm on code, message, file, line, and start column; their end columns still covered the original expression instead of the three-character replacement. This does not run edited Rust code in a resident test executable.

The [original whole-crate sweep](../data/ruff-parser-whole-analysis.json) found and repaired 47 supported sites in the library and 52 in the test build, with no failed repairs; these counts overlap. It still reran borrow checking for every named function: all 912 in the library and all 1,601 in the test build. After distinguishing queries that access one-use compiler values from queries that only ensure those values are available, the [new sweep](../data/ruff-parser-whole-analysis-selective.json) preserved all 47 and 52 error/repair pairs. Median borrow-check reruns fell to 177 of 912 (range 1–317) and 177 of 1,601 (range 1–938). All 47 production and 52 test-build errors were independently compared with freshly started compilers. This demonstrates selective reuse during whole-crate analysis; it is not an end-to-end Cargo timing result.

The [timed comparison](../data/ruff-parser-timing.json) uses 20 rounds after two warmups for three production edits: Unicode identifier detection, octal string parsing, and expression parsing. In each of 120 paired revisions, the resident compiler and a freshly started instance of the same patched compiler both request whole-crate analysis. The failing edits report exactly one matching error; the repairs are clean. The measurements were collected on an Apple M5 Max with 128 GB of memory.

| Transition           | Warm resident median | Fresh compiler median | Warm resident p95 | Fresh compiler p95 |
| -------------------- | -------------------: | --------------------: | ----------------: | -----------------: |
| Error-producing edit |                13 ms |                582 ms |            111 ms |             744 ms |
| Clean repair         |                36 ms |                608 ms |            130 ms |             769 ms |
| Both                 |                26 ms |                598 ms |            128 ms |             769 ms |

The resident measurement starts when the harness sends an edit instruction and ends when diagnostics are ready; it includes communication, invalidation, and whole-crate analysis. Starting and warming the resident compiler cost 642 ms. The fresh measurement includes process startup, parsing, analysis, and exit. Neither measurement includes Cargo, metadata emission, code generation, or linking; both disable disk incremental compilation. The resident compiler patches retained HIR, so this original measurement does not include receiving and parsing edited source text; diagnostic range ends and rendered text reflect the original source. The design follows the warmup and alternating edit pattern used by [ty's incremental benchmark](https://github.com/astral-sh/ruff/blob/fd5d636bdd58a5a42e0212988e1cdf710eec8558/crates/ruff_benchmark/benches/ty.rs#L126-L165) and [Salsa's dataflow benchmark](https://github.com/salsa-rs/salsa/blob/ba08e3fe9a7e4d332d9130753109b931baa9a7fa/benches/dataflow.rs#L137-L172). [ty's language-server benchmark](https://github.com/astral-sh/ruff/blob/fd5d636bdd58a5a42e0212988e1cdf710eec8558/scripts/ty_benchmark/src/benchmark/test_lsp_diagnostics.py#L282-L340) is the reference for the source-edit experiment below.

The separate [ordinary Cargo measurement](../data/ruff-parser-cargo-timing.json) keeps Ohm's defaults and disk incremental compilation enabled. Ten rounds after two warmups produced 30 error edits and 30 clean repairs. End-to-end `cargo +ohm check -p ruff_python_parser --lib` took 204 ms median for errors (413 ms p95) and 202 ms for repairs (329 ms p95); ten warm no-op checks had a 69 ms median. The measured process includes Cargo and normal Rust check output; the source-file write is outside the timer. These Cargo numbers are a useful developer baseline but do not mean the prototype is a resident Cargo command: its own timer still starts from a predefined HIR edit rather than a changed source file.

The [source-edit experiment](../data/ruff-parser-source-timing.json) extends this benchmark boundary to actual file writes. Its client sends a revision and a path; the compiler process reads and parses the saved Rust module and independently identifies eligible edits. Unsupported revisions are explicitly routed to a fresh compiler. This includes signature changes and edits that might change source import usage, since native body invalidation does not rerun unused-import analysis. The client keeps using a fresh compiler for subsequent saves until the resident compiler can accept the current contents of every file with an unsupported edit. Trivia-only shifts are retained only within the active owner and in files whose macro and attribute forms pass a conservative allowlist; ambiguous diagnostic source mappings and combined body-and-surrounding-trivia edits also fall back. Macro expressions are unsupported, as are body edits that might shift a custom macro's line or column. The driver compares every source-bearing error and warning against an independently started compiler, including all spans, source text, child diagnostics, and plain rendered output. It also checks that a diagnostic that already existed survives an unrelated edit and repair, including while the service is falling back. The warm Cargo comparison receives the same source revisions and keeps disk incremental compilation enabled. This experiment still embeds private compiler APIs and is not a resident Cargo command.

Twenty measured rounds after two warmups across three suites produced 640 saves. Every diagnostic matched both a fresh instance of the patched rustc and ordinary warm Cargo. Timings include the actual file write:

| Route                           | Saves | Prototype median | Prototype p95 | Warm Cargo median | Warm Cargo p95 |
| ------------------------------- | ----: | ---------------: | ------------: | ----------------: | -------------: |
| Native semantic edit            |   240 |            58 ms |        290 ms |            288 ms |         761 ms |
| Native unchanged or trivia-only |   200 |             4 ms |          9 ms |            255 ms |         700 ms |
| Fresh fallback                  |   200 |           755 ms |      2,160 ms |            259 ms |         729 ms |

Native semantic edits were 4.95× faster at the median than their paired Cargo runs; their 58 ms median met the 100 ms target, but their 290 ms p95 missed the 200 ms target. The curated corpus deliberately exercises fallback: 31.25% of these saves fell back, which is not an estimate of real edit coverage. An unchanged save still writes the file; this is not comparable to the earlier 69 ms Cargo command that did not write a file. Each suite starts with clean source and establishes its persistent diagnostic before the independent edit; this does not establish startup behavior on an already broken checkout. The output still excludes metadata emission, code generation, linking, and test execution.

The [one-test experiment](../data/ruff-parser-resident-test.json) uses Cargo's captured Ruff unit-test invocation, including `--test` and executable emission. It starts with the private `StringParser::parse_octet` function: replacing its final expression with `'x'` still compiles, but changes observable behavior. A `build` request leaves the resident loop and hands the retained compiler context to ordinary rustc code generation and linking once. The benchmark then runs only `string::tests::test_escape_octet` as a new process. Each build consumes its compiler; a new worker for the repair warms on canonical source and replays the previous edit before measuring the save of the original source. This isolates whether edited resident state reaches an actual executable; repeated code generation in one process, integration tests, and doctests remain separate milestones.

Five measured rounds after one warmup produced 25 transitions. Both modes passed the unchanged test, failed it after the compiling behavior change, passed after repair, rejected `E0308` without running the existing executable, and passed after repairing that error. Both changed the executable's contents on the behavior edit and repair. Median save-to-result timings were:

| Transition                          | Ready resident compiler | Warm Cargo |
| ----------------------------------- | ----------------------: | ---------: |
| Save unchanged source               |                  1.90 s |     0.14 s |
| Behavior edit: test fails           |                  2.04 s |     1.23 s |
| Behavior repair: test passes        |                  1.99 s |     0.98 s |
| Rust type error: test skipped       |                  0.13 s |     0.36 s |
| Rust type-error repair: test passes |                  2.00 s |     0.81 s |

Across the behavior edit and repair together, the ready resident compiler took 2.00 s median versus 1.07 s for Cargo. Native rustc code generation took 1.71 s, linking 112 ms, and the test process 80 ms. Native workers use the patched resident graph with rustc disk incremental disabled; ordinary warm Cargo keeps it enabled. Restarting and warming each native worker cost 1.19 s median outside save-to-result, and replaying the behavior edit for repair cost another 78 ms median outside the repair timer. With five observations per transition, the nearest-rank p95 is simply the slowest observation; this establishes functionality, not a test-build speedup.

First build the companion patched Ohm compiler and its matching standard, test, procedural macro, and rustdoc libraries in the Rust checkout:

```sh
python3 x.py build --stage 1 --build-dir /path/to/bootstrap \
  compiler/rustc library/std library/test library/proc_macro src/tools/rustdoc
```

Then run both modes from this checkout. Supply a Ruff Git checkout containing the pinned revision, an empty disposable archive directory, a Cargo target directory, and the bootstrap host's stage-one directory:

```sh
python3 experiments/resident-checker/ruff/run_tests.py \
  --repo /path/to/ruff \
  --checkout /path/to/disposable/ruff-archive \
  --target-dir /path/to/isolated/cargo-target \
  --stage /path/to/bootstrap/aarch64-apple-darwin/stage1 \
  --output /path/to/results
```

The runner archives the exact commit without writing to the checkout passed as `--repo`. It runs package tests and doctests separately, then writes `summary.json`, each Cargo log, and each captured compiler command under the output directory. Use `--mode graph` or `--mode default` to run only one configuration, or `--offline` when all Cargo dependencies are already cached. The Python standard library and the `cargo +ohm` command are required; the wrapper scripts must retain their executable Git file mode.

In graph mode, the Cargo wrapper appends `-Zohm-resident-query-graph` to the parser library, parser unit-test target, custom syntax-fixture executable, and inline-test generator. Unrelated dependencies compile normally. The runner also passes the flag through rustdoc and checks the argument files received by its actual doctest compiler subprocesses. Both modes disable Cargo's disk incremental compilation.

Use the captured library invocation to run the [real-parser edit driver](edits.rs). It warms whole-crate analysis, then changes and restores a lexer function and an inherent string-parser method twice in one compiler context. It records actual type- and borrow-check provider counts, diagnostic spans, and unrelated control functions:

```sh
python3 experiments/resident-checker/ruff/run_edits.py \
  --bootstrap /path/to/bootstrap \
  --capture /path/to/results/graph-test/captures/ruff_python_parser.lib.json \
  --output /path/to/resident-edits
```

Keep the archive and Cargo target used for `run_tests.py` in place, because the captured invocation points to them. Pass `--target` for a bootstrap host other than `aarch64-apple-darwin`. The driver writes `targeted.json` and both raw compiler streams. `--fresh-reference /path/to/fresh-diagnostics` optionally compares the errors against rustc JSON logs named `parser-identifier-type.stderr` and `string-method-type.stderr`; native-only reproduction does not need those logs.

Use the same captured library invocation for the paired timing; this runner creates two fresh disposable Ruff archives and keeps raw samples, commands, and diagnostics under its output directory:

```sh
python3 experiments/resident-checker/ruff/measure.py \
  --bootstrap /path/to/bootstrap \
  --capture /path/to/results/graph-test/captures/ruff_python_parser.lib.json \
  --repo /path/to/ruff --output /path/to/paired-timings \
  --compiler-revision <patched-compiler-git-sha>
```

Measure normal warm Cargo separately. This command uses its own disposable archive and target, leaves Cargo incremental compilation enabled, and writes raw command output and samples alongside its summary:

```sh
python3 experiments/resident-checker/ruff/measure_cargo.py \
  --repo /path/to/ruff --checkout /path/to/disposable/cargo-ruff \
  --target /path/to/isolated/cargo-target \
  --stage /path/to/bootstrap/aarch64-apple-darwin/stage1 \
  --output /path/to/cargo-timings \
  --compiler-revision <patched-compiler-git-sha>
```

Measure from actual source-file writes through complete diagnostics with the same compiler capture. The output contains independent resident, fresh-oracle, and warm Cargo archives and raw per-revision diagnostics; the Cargo target can be shared across reruns of this benchmark:

```sh
python3 experiments/resident-checker/ruff/measure_source.py \
  --bootstrap /path/to/bootstrap \
  --capture /path/to/results/graph-test/captures/ruff_python_parser.lib.json \
  --repo /path/to/ruff --cargo-target /path/to/isolated/cargo-target \
  --output /path/to/source-timings \
  --compiler-revision <patched-compiler-git-sha>
```

To measure the one-test code-generation proof, use the actual unit-test capture rather than the library-only check capture. The benchmark writes raw compiler, Cargo, and test output as well as separate native code-generation and linker timings:

```sh
python3 experiments/resident-checker/ruff/measure_test.py \
  --bootstrap /path/to/bootstrap \
  --capture /path/to/results/graph-test/captures/ruff_python_parser.test.json \
  --repo /path/to/ruff --cargo-target /path/to/isolated/cargo-target \
  --output /path/to/test-timings \
  --compiler-revision <patched-compiler-git-sha>
```

The separate [build-guard runner](run_test_build_guards.py) uses the same driver with small Rust fixtures. All [nine recorded cases](../data/ruff-parser-resident-test-guards.json) passed, including stale revision numbers, disk changes that were never checked, unsupported edits, and a compile error that survives a successful edit in another file. It keeps a sentinel executable in place on rejected builds to verify that it is neither replaced nor run:

```sh
python3 experiments/resident-checker/ruff/run_test_build_guards.py \
  --driver /path/to/test-timings/source-driver \
  --stage /path/to/bootstrap/aarch64-apple-darwin/stage1 \
  --output /path/to/build-guard-results
```
