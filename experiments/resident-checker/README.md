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

The drivers default to `aarch64-apple-darwin`; pass `--target` for another supported target. They use private compiler metadata and must be built against the same patched compiler. These results do not establish arbitrary source-edit support, Cargo integration, or whole-project performance. The source text held by the resident compiler is still the original; the uv comparison checks structured diagnostics and mapped locations, not unchanged raw rendered source snippets.
