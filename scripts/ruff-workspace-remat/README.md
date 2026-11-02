# Deferred register-interval updates on a Ruff edit

The primary comparison counts retired user instructions across an ordinary signed Ohm build of the real Ruff workspace library. The two arms differ only in the root compiler's LLVM option. LLVM normally updates a rematerialized source interval immediately when it has fewer than 100 remaining copy uses. The treatment reduces that threshold to one.

Both workers start with the signed GNU SDK and the same pinned Ruff commits. Each measures both arms on four physical CPUs in the opposite order from the other worker. Every arm starts with an empty target, build directory and private Cargo home. The measured sequence builds the old source, applies the genuine option edit, repeats the build, introduces a type error and repairs it. A separately empty history builds the new source. Each successful state links and runs an option reader. The measured native client also queries and formats the changed option, a sibling and a missing option. This test covers that part of Ruff's runtime.

The primary observation is the first build after the real edit. The initial build, unchanged build, invalid build, repair, empty reference and runtime reader are separate outcomes. The hardware clocks must report equal enabled and running time. All reported artifacts must agree with the locked dependency graph, the root's actual rustc invocation must carry the selected profile, and the negative compile must report E0308. The shared remote branch accepts a manual dispatch naming its exact head.

Two completed counterbalanced pairs support an initial decision about replication. A performance PR needs independent repeat runs, native behavior checks on the changed isort deserializers, and a comparison of the compiler work needed for testing.
