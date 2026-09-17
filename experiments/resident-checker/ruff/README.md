# Ruff parser test-suite compatibility

The [recorded run](../data/ruff-parser-tests.json) runs all targets and doctests for `ruff_python_parser` at Ruff revision `fd5d636bdd58a5a42e0212988e1cdf710eec8558`. Both the patched Ohm compiler with its resident query graph enabled and the same compiler with the graph disabled passed 245 unit tests, 557 syntax fixtures, one inline-test generator, and 10 doctests: 813 in each mode, with no failures, ignored tests, or filtered tests. The package has no optional features; the reproduction still requests `--all-features`.

This checks compatibility of the instrumented compiler with the unedited parser and runs Ruff's actual test executables. Cargo starts compiler processes normally; these results do not establish reuse or correct invalidation across source edits in one compiler process.

The [separate edit results](../data/ruff-parser-edits.json) record an initial resident sweep: the 912 named library functions and 1,601 named test-build functions checked clean, but the original edit APIs accepted none of the candidate sites. Fresh compilers independently verified eight edits that should fail compilation and four edits that compile but should fail a targeted Ruff runtime test.

An extended editor then changed the real `lexer::is_unicode_identifier_start` function and `StringParser::parse_octet` method. Each edit produced `E0308`, recovered, produced the error again, and recovered again in the same compiler process. Four unrelated functions kept their type and borrow results. A fifth, the const function `is_complex_number`, retained its type result but reran borrow checking after all eight revisions: its MIR depends on whole-crate analysis, which depends on the edited module's attribute check. The resident errors agreed with fresh Ohm on code, message, file, line, and start column; their end columns still covered the original expression instead of the three-character replacement. This does not run edited Rust code in a resident test executable.

The selected-function driver does not demonstrate whole-crate cache reuse. The [whole-crate edit sweep](../data/ruff-parser-whole-analysis.json) found and repaired 47 supported sites in the library and 52 in the test build, with no failed repairs; these counts overlap. It requests whole-crate analysis after each edit and reruns borrow checking for every named function: all 912 in the library and all 1,601 in the test build. Type checking is more selective. Five production edits were also independently compared with a fresh compiler. The full test suite and resident diagnostics pass, but this path is not yet evidence for faster whole-crate iteration.

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
