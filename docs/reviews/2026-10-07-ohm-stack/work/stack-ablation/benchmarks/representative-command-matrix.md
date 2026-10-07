Primary results are the timing of each named command: cold, warm no-op, and after a representative source edit. History totals are context. No project test execution is timed.

| Project / working directory | Ordinary check command | Ordinary build command | Original profile and edits |
| --- | --- | --- | --- |
| Ruff / repository root | `cargo check --locked --offline --lib -p ty_python_semantic -p ty_python_core` | `cargo build --locked --offline --lib -p ty_python_semantic -p ty_python_core` | Keep original dev opt-level 1, LTO off, line-table debug. Measure each of the three original recursive-attribute/fixed-point implementation edits separately. |
| uv / repository root | `cargo check --locked --offline --lib -p uv-pypi-types -p uv-client` | `cargo build --locked --offline --lib -p uv-pypi-types -p uv-client` | Keep the fixed repository profiles, without new profile overrides. Measure the original parser implementation, parser simplification, and compatibility-test edit separately; the last edit may be inactive for these library commands. |
| Codex / `codex-rs` | `cargo check --locked --offline --lib -p codex-tui` | `cargo build --locked --offline --lib -p codex-tui` | Keep the fixed repository profiles. Measure the original transcript bookkeeping, rendering, and chat-widget invalidation edits separately. |

These are the already accepted five-command recipes: cold command, warm no-op, then the same command after each of the three unchanged original edits. The two operations use separate sources and cache histories. Each cold command starts with empty private target and build-store directories; warm commands retain only their own history. Both arms retain the original lockfiles, setup patches, trust settings, and all Ohm defaults except the declared candidate axis. Eight Cargo jobs. Existing campaigns retain six fixed counterbalanced pairs per project; new screens use two, one in each arm order.

| Operation | Existing ordinary command and working directory | Per-command phases |
| --- | --- | --- |
| Formatter, all three projects | `cargo fmt --all`; checking uses `cargo fmt --all -- --check`. Repository root for Ruff/uv, `codex-rs` for Codex. | Cold format, warm format/check, root edit, direct leaf edit, four-file edits, and shared-config edit/revert. Report each named format/check phase separately. Existing real batching/fallback and config-read coverage is retained; no new performance fixture. |
| Clippy, Ruff | `cargo clippy -p ty_python_semantic -p ty_python_core --all-targets -- -D warnings`, plus the five original compatibility allowances recorded in `ruff-rust-1.99.json`. Repository root. | Cold, warm no-op, first original implementation edit, and the existing API-stable dependency edit. |
| Clippy, uv | `cargo clippy -p uv-pypi-types -p uv-client --all-targets --locked -- -D warnings -A clippy::doc_markdown -A clippy::double_must_use`. Repository root. | Same four existing phases, reported individually. |
| Clippy, Codex | `cargo clippy --tests -p codex-tui -- -D clippy::redundant_closure_for_method_calls`. `codex-rs`. | Same four existing phases, reported individually. Test targets are linted, not executed. |

Compiler metadata/cache/resolver candidates start with check; codegen/allocator/partition/layout/debug candidates use build. A candidate that affects both can receive the two separate ordinary operations. The default proc-macro-cache comparison uses the same shipping compiler/Cargo and changes only its already accepted cache-default flag. Resolver-cache activation uses original shipping Cargo and only `CARGO_EXPERIMENTAL_RESOLVE_CACHE=0` in the disabled arm. No default test-compilation matrix or synthetic timing workspace is added.

The exact source/edit/setup closure remains the accepted artifact 853b657c and original ten fixture/patch files. Broad native correctness and shortcut activation have already been reviewed independently; their untimed evidence does not become a command-latency claim.
