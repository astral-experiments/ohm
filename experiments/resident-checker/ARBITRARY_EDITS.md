# Arbitrary edits in a resident compiler

The target is ordinary Rust iteration: edits to function bodies and signatures, multiple files, imports, item creation and deletion, macro definitions and invocations, and broken intermediate source must all use the normal compiler semantics. The older private-body edit implementation is useful for measuring potential reuse, but adding more handwritten HIR transformations is not the intended architecture for this target.

The first correctness baseline uses a persistent dispatcher and runs the normal rustc frontend for every source revision. Each invocation creates a fresh compiler session, source map, resolver, type context, and query arena. Ordinary rustc disk incremental compilation is enabled in a dedicated output directory; the experiment does not retain semantic query values in memory. Changes are not filtered by a source-edit allowlist. The dispatcher defaults to a fresh compiler subprocess per revision. The target can emit ordinary debugger line tables because the new session uses the current source files.

The subprocess boundary matters: rustc keeps procedural-macro dynamic libraries loaded in a compiler process. A procedural macro can hold mutable globals across invocations; even an unchanged macro binary can then produce results that differ from ordinary fresh rustc. The opt-in `OHM_ARBITRARY_REUSE_PROCESS=1` skips isolation for research on inputs independently known not to use procedural macros; it is not a generally correct alternative. Backend selection and LLVM initialization also have process-wide state, so the driver fixes all compiler options for its lifetime. Cargo targets, compiler options, dependency changes, build scripts, and generated-file orchestration are not handled by this prototype; the client supplies one fixed compiler invocation and its dependencies.

The [procedural-macro regression](data/arbitrary-proc-macro-isolation.json) builds one macro library with an internal counter and changes its consumer's source between requests. With the default isolation, each revision produced a new executable that passed its externally supplied expected value. Explicit process reuse failed on the second request with a diagnostic from the macro; it preserved and never ran the previous executable. Disk incremental compilation was disabled in this guard to demonstrate that retained process state was sufficient to cause the difference.

To build the experimental driver against a stage-1 rustc bootstrap:

```sh
python3 experiments/resident-checker/ruff/build_revision_driver.py \
  --bootstrap /path/to/bootstrap --output /path/to/driver
```

To reproduce the procedural-macro guard:

```sh
python3 experiments/resident-checker/ruff/check_revision_proc_macro.py \
  --driver /path/to/driver/revision-driver \
  --stage /path/to/bootstrap/aarch64-apple-darwin/stage1 \
  --output /path/to/proc-macro-results
```

Run the macro-free fixture against the same rustc, using independent incremental directories for the dispatcher and fresh compiler control:

```sh
python3 experiments/resident-checker/ruff/measure_arbitrary.py \
  --driver /path/to/driver/revision-driver \
  --rustc /path/to/bootstrap/aarch64-apple-darwin/stage1/bin/rustc \
  --output /path/to/fixture-results --compiler-revision <compiler-git-sha>
```

The [synthetic report](data/arbitrary-synthetic.json) records 54 measured revisions over three rounds after one warmup. The fixture has no procedural macros, so it can explicitly reuse one compiler process. Every outcome, reported primary source location, and normalized test output matched a fresh rustc. Median compiler time was 158 ms versus 205 ms overall; successful compiles were 174 ms versus 240 ms, and compile errors were 40 ms versus 94 ms. Existing test executables survived 15 erroneous revisions in each mode, including warmup, and were never executed after a compile failure. The comparator is direct rustc, not Cargo; both have separate ordinary disk incremental directories, and the worker does not retain semantic query values.

Use the normal isolation policy for the pinned real Ruff parser unit-test target. The benchmark runs all 245 parser unit tests after successful builds by default and compares normalized source diagnostics and libtest counts with an independent fresh compiler; `--selected-test` narrows it to the exact octet test. It deliberately begins with a syntax error and includes a behavior regression, coordinated method-signature and call-site edits, an import rename, declarative macro creation and changes, and creating, deleting and recreating an actual source module. The cases are separate edit and repair sequences, not a claim about arbitrary combinations:

```sh
python3 experiments/resident-checker/ruff/arbitrary_ruff.py \
  --driver /path/to/driver/revision-driver \
  --stage /path/to/bootstrap/aarch64-apple-darwin/stage1 \
  --capture /path/to/captures/ruff_python_parser.test.json \
  --repo /path/to/ruff --output /path/to/ruff-results \
  --compiler-revision <compiler-git-sha>
```

The [Ruff report](data/arbitrary-ruff.json) records 28 measured revisions over two rounds after one warmup. Each measured side used 28 distinct compiler processes, while the dispatcher stayed alive. Every normalized source diagnostic and libtest count matched: 22 revisions passed all 245 tests, two deliberate macro regressions each passed 243 and failed the same two octal-escape tests, and four source compilation errors never launched an old executable. Median source-save-to-result was 986 ms through the dispatcher versus 972 ms for independent fresh rustc; p95 was 2,001 ms versus 1,952 ms. This is a correctness baseline with about 1.4% median overhead, not a speedup or a comparison with warm Cargo. The package test target emitted debugger line tables; its prebuilt dependencies were identical on both sides.

The [compiler profile](data/arbitrary-ruff-profile.json) uses rustc's `-Zself-profile` and `rust-lang/measureme` to expose incremental loading as well as ordinary compiler work. Of 30 measured revisions, 24 passed all 245 tests, two deliberately failed the same two tests, and four compiler errors never ran tests. For passing revisions, profiled median wall time was 704 ms compiling and 80 ms running tests. Internal median activities were 27 ms to load the dependency graph, 4 ms for its lazy reverse indexes, 3 ms to open the serialized query cache, and 25 ms in exclusive lazy query-answer decoding. Macro expansion including module parsing took 111 ms; the 21 actual procedural-macro calls made by every passing revision took only 5 ms combined. Name resolution took 21 ms, type checking 24 ms, LLVM 202 ms, and the linker invocation 81 ms. These activities can overlap or nest and cannot be added; profiling overhead is included, and a separate unprofiled comparison is needed for performance claims.

To reproduce the profile, install `rust-lang/measureme`'s `summarize` at version `12.0.3`, then run:

```sh
python3 experiments/resident-checker/ruff/profile_arbitrary.py \
  --stage /path/to/bootstrap/aarch64-apple-darwin/stage1 \
  --capture /path/to/captures/ruff_python_parser.test.json \
  --repo /path/to/ruff --output /path/to/profile \
  --summarize /path/to/summarize --compiler-revision <compiler-git-sha>
```

Rustc already maps its on-disk incremental cache. The separate `--pin-incremental-pages --require-locked-pages` control in `arbitrary_ruff.py` explicitly locks read-only mappings of the last finalized dependency graph, query cache, and work-product manifest in the dispatcher. It reports page locking and refresh costs, not semantic reuse. On macOS, rustc normally creates a clone of the finalized directory whose files have different identities; locking the original does not establish that the next rustc process opens the same memory-backed file.

The [companion compiler prototype](https://github.com/astral-sh/ohm-rust/pull/145) introduces an explicitly enabled extra dependency-graph file. Each successful build writes it for the next revision; a fresh compiler validates its source generation and checksum, maps immutable value fingerprints and graph-edge bytes, and still reconstructs process-local nodes and lookups. It keeps the stock graph for fallback and does not retain query answers, type contexts, or procedural-macro state. On macOS it hard-links this immutable file into the otherwise cloned working directory; if a shared file cannot be established, it falls back to the stock graph. The paired `--flat-dep-graph` mode enables the prototype only on the dispatcher side and requires actual write and load traces while keeping the fresh control disabled.

The [fresh-process guard](data/arbitrary-flat-dep-graph-guards.json) verifies 11 distinct rustc processes. Five loads independently observed the same APFS file identity between the last finalized generation and the new working generation. Deleting, corrupting, and substituting a wrong-generation graph each fell back to the stock representation and recovered. A compile error left the prior executable unchanged and never ran it; the control with the feature disabled emitted no sidecar events.

The [paired Ruff comparison](data/arbitrary-flat-dep-graph.json) used the entire 245-test suite over 28 measured revisions after one warmup round. The optional graph loaded on all 28; all 24 successful compilations wrote the next graph, with no fallback or write failures. All outcomes and normalized source diagnostics matched the control, including 22 all-green test runs, two deliberately failing runs, and four compiler errors that never ran the old executable. The candidate was faster in only 11 of 28 matched revisions; the median paired comparison favored stock by about 3.9%, and both individual rounds favored stock. Successful compilations took 2,014 ms median through the candidate versus 1,901 ms for stock; errors took 277 ms versus 237 ms. The misleading pooled medians went the other way (1,669 ms versus 1,775 ms), and candidate p95 was 2,761 ms versus 2,737 ms. This result does not establish a speedup and does not justify enabling the extra graph format; generating, hashing, and validating it still costs time on every revision.

Rustc's existing incremental format represents query dependencies using stable cross-session keys and remaps persisted values, source locations and definitions into a fresh compiler context. That remains a possible way to retain work without sharing pointers into an old compiler arena. It still cannot eliminate crate-wide macro expansion and name resolution or replace procedural-macro isolation. The profile suggests that a dependency-graph-only change has limited upside; a fresh-Cargo comparison and equivalent measurements for an isolated macro host remain open.
