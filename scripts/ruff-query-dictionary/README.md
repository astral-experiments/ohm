# Stable query identities in two signed Ruff builds

This manual diagnostic builds the complete Ruff CLI from two empty, isolated build/target pairs, at b5dba861cc38e3f7fb4524c9ceba3e01a474ea13 and 7b13f01ba1569887a25670820764b24c206da8e5. It authenticates the published GNU Ohm -22 Cargo, rustc, matching driver, libraries, and all 505 external package archives. Only the ruff_workspace library's rustc receives -Zself-profile and -Zself-profile-events=default,query-keys.

The 49 terminal rejection occurrences in keys.json select 30 distinct (dependency kind, 128-bit key) pairs. Another 1,396 pairs appeared elsewhere in the recorded paths. Run 41414492188 did not observe 75 inherited descriptors and failed its admission test. These keys supply a provisional sample. The two new cold builds provide independent naming evidence.

Each wrapper freezes its current graph and profiler output before returning to Cargo. The reader checks the compiler PID and its complete argv inside the profile and checks both raw files against their recorded sizes and SHA-256 digests. It joins each virtual ID only to that process's current graph, recording duplicate values, absent names, original text and any ambiguous result. Cross-history matching uses the full stable pair. A stale or swapped profile or graph must fail. A typed Rust consumer, contradictory E0308 checks and Ruff CLI behavior establish which actual source revision compiled.

RUSTC_WRAPPER is specific to this diagnostic. Each raw rustc argument and native owner rlib and metadata digest is retained. The A owner, feature and codegen configuration is checked against the original A from the refused selection trace. No hardware counters are collected.

After extracting the complete workflow artifact into an empty directory, run the versioned reader with Python 3.11+ on Linux.

    python3 -IB scripts/ruff-query-dictionary/reopen.py /path/to/extracted-artifact /path/to/new-result.json

For an ABI or symbol name, the result distinguishes the actual instance discriminant, empty versus instantiated generic-argument lists, closures, shims, and nondefault ABI contexts. An empty ordinary item supplies a candidate key shape. This diagnostic neither makes an opaque hash invertible nor proves that rustc can reconstruct a key from a dependency graph alone.
