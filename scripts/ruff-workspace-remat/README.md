# Guarded LLVM register coalescing on Ruff edits

This study compares two physical stage1 Rust compilers on Linux x86-64. The historical arm names `normal` and `defer` select the parent compiler and the compiler with the guarded register coalescer. Both use the same signed Ohm Cargo and LLVM SDK. The retired-instruction counter covers Cargo and its children. The worker records the actual rustc invocations, shared libraries and file digests. The compiler source and artifact identities are in `factory.json` and the linked factory receipts.

The primary measurement is the ordinary `cargo build` after the real Ruff #28106 edit to the workspace library. Six fresh workers each compile both arms, with three workers in each order. A separate downstream executable checks the edited option documentation, its unchanged sibling and an absent option. An independent clean build, a source type error, its repair and a subsequent unchanged build guard against stale artifacts. The unchanged command is also reported separately.

Two additional workers use opposite arm orders for Ruff #27836 and `cargo test --no-run`. A separate invocation lists and executes the changed test after compilation. It must pass after the edit, fail on deliberately mismatched sources and match the independently clean executable after repair. The instruction counter excludes the test executions.
