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

For performance beyond this baseline, the next research boundary is rustc's existing incremental format. It represents query dependencies using stable cross-session keys and remaps persisted values, source locations and definitions into a fresh compiler context. A session-independent memory cache built around that representation could retain work without sharing pointers into an old compiler arena. It still would not remove crate-wide macro expansion and name resolution, and it cannot replace procedural-macro isolation. Profiling and a fresh-Cargo comparison across the full parser suite should determine which cost to optimize first.
