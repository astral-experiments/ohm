# Resident compiler checks

This experiment measures whether an Ohm compiler can keep its in-memory query results across Rust source edits, report errors that appear outside the edited function, and preserve unaffected checks. It is not a `cargo check` mode. The [companion compiler draft](https://github.com/astral-sh/ohm-rust/pull/144) contains the implementation; this directory contains the reproduction and compact evidence.

The [synthetic fixture results](data/synthetic.json) record four alternating failing/clean revisions in each fixture, always using one compiler context per fixture. An ordinary private function emits `E0308` locally; a `const fn` used as an array length emits `E0308` downstream; and changing the hidden type of an `impl Sized` result emits `E0277` in a caller that requires `Send`. A fourth fixture requires two callers sharing an indirect trait obligation to report and clear the error independently. Unchanged direct and transitive callers, another opaque type and its caller, the generic helper, and a separate control retain their original type-result pointers and type/borrow provider counts.

To build the patched compiler and its matching standard library in the companion Rust checkout:

```sh
python3 x.py build --stage 1 --build-dir /path/to/bootstrap \
  compiler/rustc library/std library/proc_macro
```

Then run the fixtures from this checkout. The runner writes raw compiler output and a full `summary.json` in the supplied output directory; the second command strips machine-specific paths and pointers from the published summary.

```sh
python3 experiments/resident-checker/fixtures/run_typed.py \
  --bootstrap /path/to/bootstrap --output /path/to/results --require-auxiliary-cache
python3 experiments/resident-checker/compact.py \
  /path/to/results/summary.json /path/to/summary.json
```

The [production `uv-pep440` result](data/uv-pep440.json) records two failures and two repairs in one compiler context. Both `parse_pre::SPELLINGS` and `parse_post::SPELLINGS` emitted `E0080` on each invalid revision and recovered; the real evaluation and allocation providers reran each time. `parse_u64`, `sortable_tuple`, and `starts_with_ignore_ascii_case` retained their type and borrow counts and their type-result pointers. The runner compared structured diagnostics with five freshly started patched compilers. A [second run](data/uv-pep440-borrow.json) additionally requested borrow checking of both enclosing parser functions after each edit; both retained their original type results and reran borrow checking without consuming stale MIR. Add `--check-parser-borrow` to reproduce this stronger mode.

To reproduce, archive uv at the pinned revision and compile its dependencies using the patched compiler. The runner changes the private `StringSet::new` assertion threshold from `20` to `0` and back and asks for both production `SPELLINGS` constants. It edits only the temporary archive, not the checkout passed to `--repo`.

```sh
python3 experiments/resident-checker/uv/prepare_uv.py --repo /path/to/uv \
  --checkout /path/to/temporary/uv --target-dir /path/to/isolated/uv-target \
  --stage /path/to/bootstrap/aarch64-apple-darwin/stage1 --output /path/to/capture
python3 experiments/resident-checker/uv/run_uv.py --bootstrap /path/to/bootstrap \
  --capture /path/to/capture/capture.json --output /path/to/uv-results
python3 experiments/resident-checker/compact.py \
  /path/to/uv-results/summary.json /path/to/uv-summary.json
```

The [complete Ruff parser suite](data/ruff-parser-tests.json) passes with the resident dependency graph enabled and disabled: 245 unit tests, 557 Python syntax fixtures, one fixture-generator integration test, and 10 doctests (813 tests total in each mode). The harness verifies the compiler option for all four parser package targets and both doctest compiler invocations. The [Ruff reproduction](ruff/README.md) and [parser edit corpus](data/ruff-parser-edits.json) also cover two real edits checked and repaired twice in one compiler context. The [whole-crate sweep](data/ruff-parser-whole-analysis-selective.json) checked and repaired 47 production edits and 52 test-build edits; median borrow checks rerun fell from the entire crate to 177 of 912 production functions and 177 of 1,601 test-build functions. These query counts establish selective reuse; they do not themselves measure end-to-end iteration speed or establish support for arbitrary edits.

The [original Ruff timings](data/ruff-parser-timing.json) measure whole-crate analysis after three private edits: 26 ms median in the warm resident compiler versus 598 ms in freshly started compilers across 120 paired revisions. A [separate end-to-end Cargo baseline](data/ruff-parser-cargo-timing.json), with Ohm defaults and disk incremental compilation enabled, took 204 ms median for errors and 202 ms for repairs; a no-op took 69 ms. That earlier resident path accepted predefined HIR edits and excluded receiving and parsing changed source text.

The [source-edit benchmark](data/ruff-parser-source-timing.json) starts before saving real Ruff source and finishes once all source-bearing diagnostics have been prepared. It checks clean edits, errors, repairs, relocated diagnostics, import and signature fallbacks, and whether an existing error survives a different file's edit, including during fallback. The service reads and parses each changed module; supported private edits reuse native state, while unsupported changes use a fresh compiler until their files return to accepted contents. All 640 saves matched fresh rustc and warm Cargo. The 240 native semantic saves took 58 ms median and 290 ms p95, versus 288 ms and 761 ms for paired warm Cargo: 4.95× at the median, but above the 200 ms p95 goal. The 200 deliberately included fresh fallbacks took 755 ms median, versus 259 ms for Cargo. This is not a resident Cargo command and does not run tests.

The [one-test experiment](data/ruff-parser-resident-test.json) sends a genuine private-body edit to a resident Ruff unit-test compiler, then hands that same compiler state to stock code generation and linking once. It invokes only `string::tests::test_escape_octet` from the emitted executable, checks that a compiling behavior edit fails and its repair passes, and checks that an actual Rust type error never launches an older executable. All 25 measured transitions matched warm Cargo. Behavior edits and repairs took 2.00 s median from a ready compiler versus 1.07 s for Cargo; native code generation took 1.71 s. Restarting and warming each compiler took another 1.19 s median outside that timer. Each build exits its compiler; repair workers replay the prior source edit before timing the repair. This establishes that retained edits reach executable machine code, not that one compiler process can produce repeated builds.

After regenerating checked-in reports, apply the repository's pinned JSON formatter:

```sh
npm exec -- prettier --write 'experiments/resident-checker/data/*.json'
```

The drivers default to `aarch64-apple-darwin`; pass `--target` for another supported target. They use private compiler metadata and must be built against the same patched compiler. These results do not establish arbitrary source-edit support, Cargo integration, or whole-project performance. The source text held by the resident compiler is still the original; the uv comparison checks structured diagnostics and mapped locations, not unchanged raw rendered source snippets.
