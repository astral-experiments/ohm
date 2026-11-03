# Why an indirect check needs its own validation

An upstream macro evaluated a constant in an indirect consumer’s function body. The consumer’s old metadata encoded neither of the upstream definitions that changed. Substituting the new upstream hash in those 2,357 bytes made the real compiler accept an invalid program.

Four tiny crates use the actual rustc candidate from the Ruff qualification. The origin crate exports the macro. The facade only reexports it. The consumer exports a normal `#[inline(never)]` function returning `u8` and uses the macro inside its body. The verdict crate calls that function. The two fixtures use the original, independently authenticated `a7fc5bc7` driver and its 66 matched SDK files. [Compiler factory](https://github.com/astral-experiments/ohm/actions/runs/41568934075)

| Observed from ordinary Cargo | Constant type fixture | Glob lookup fixture |
|---|---|---|
| Real edit | Change `VALUE: u8` to `VALUE: &str` | Add a second `VALUE: u8` through another glob import |
| Warm and independently empty edited check | E0308 | E0659 |
| First unchanged and repaired checks | Fresh, then success | Fresh, then success |
| Definitions with changed or added public rows | Origin crate root and `VALUE` | Origin crate root, `second` and new `second::VALUE` |
| Successful previous consumer graph | 571 nodes, 883 edges | 615 nodes, 1,019 edges |
| Actual direct query edge to `type_of` | `typeck_root(consumer::result)` 838 → 837 | `typeck_root(consumer::result)` 885 → 884 |

The producer’s public-global fingerprint, the exported macro’s per-definition fingerprint and the facade’s public crate hash agreed before and after both edits. Every original, edited and repaired metadata file had zero declared traits, trait-implementation groups, incoherent groups and inherent-implementation slots. We decoded those arrays in the actual metadata.

In the constant fixture, neither changed eight-byte definition identity occurred anywhere in the old consumer or facade metadata. The compiler writes these identities as literal little-endian bytes. In the glob fixture, the old consumer held one occurrence of the bytes for the origin’s crate root. Both the competing module’s identity and its new member’s identity were absent. The two saved validation roots reached the previously selected `first::VALUE`, with no prior query keyed to the newly populated `second` module. Rustc also kept `analysis` and `resolver_for_lowering_raw` nodes with zero serialized outgoing edges. Both queries are declared `eval_always`. [Source declaration](https://github.com/astral-experiments/ohm-rust/blob/259ad7069e47eaf08cf106f187b2b6393f7fd7c2/compiler/rustc_middle/src/queries.rs#L196-L205)

The real compiler first accepted the original producer, facade and consumer metadata. With the changed origin and facade, the original consumer correctly yielded E0460. In a fresh copy of the consumer, exactly the 16-byte required `origin` hash at byte offset 1,017 was replaced. All own public and private hashes, definition and expansion rows, and every other required dependency were checked again. The next real compiler invocation accepted both copies and wrote metadata, although ordinary Cargo rejected the source with E0308 and E0659. The repair in each fixture passed independently from empty and produced the same physical origin, facade and consumer metadata as the repaired warm state.

The earlier graph records a real incoming read for the macro constant. A preflight using only the reachable definition IDs in the emitted artifact, public-global hashes and existing trait cohorts would miss it. A preflight taking the ordinary existing dependency graph must honor the coarse upstream metadata input hash, run the current resolver and execute native procedural macros when present. That is the boundary demonstrated by these fixtures. [Raw metadata, graphs and diagnostics](originals.tar.xz)

## Reopen or rerun

The first command validates the sealed 27 KiB raw corpus and both typed dependency graphs, and optionally repeats all six metadata-load invocations against the real SDK. The second builds both source histories from scratch. Use the matched Rust source and candidate SDK from the parent qualification.

```sh
python3 -IB verify.py --rust-source /path/to/matched/rust --sdk /path/to/candidate/sdk
python3 -IB run_cargo.py --sdk /path/to/candidate/sdk --work /path/to/new/fixture
```
