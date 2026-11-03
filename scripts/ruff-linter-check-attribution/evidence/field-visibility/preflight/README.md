# Can the previous dependency graph justify skipping an entire indirect check?

The existing graph can identify specific external inputs that must be checked again. A complete verdict before expansion would also have to account for actual native macro executions under current inputs. In the signed `ty_python_semantic` check, the process ran native Salsa macros. Their inputs can include native state or filesystem reads that the Rust dependency graph does not record. Skipping this compiler would also skip those executions. [Actual signed check](https://github.com/astral-experiments/ohm/actions/runs/41573331247), [the native FFI counterexample and compiler fix](https://github.com/astral-experiments/ohm-rust/pull/244)

## Two real previous check graphs

We scanned all sparse records, authenticated the whole input, checked each record's seek-table entry, reconstructed every footer kind count and verified the total edge count. Twelve queries have `DefId` keys, including `type_of`, `def_kind`, `fn_sig`, `trait_impls_of` and `module_children`. The local stable crate ID is the single common prefix of every `typeck_root` key. Foreign keys in these twelve kinds count once regardless of how many queries refer to the same definition. [Complete inputs, schema bindings and counts](census.json), [query definitions](https://github.com/astral-experiments/ohm-rust/blob/008a21ac0d750dc9a1c18b7959d7e7984c03d887/compiler/rustc_middle/src/queries.rs)

| Signed Ruff check graph | Nodes | Edges | Typeck / borrowck roots | Distinct foreign definitions in 12 kinds | With an `extern_def_public_hash` row in the same previous graph | Whole external crate input rows |
|---|---:|---:|---:|---:|---:|---:|
| `ruff_python_ast` | 563,048 | 3,575,690 | 4,790 / 4,697 | 3,125 | 291 | 43 |
| `ruff_python_parser` | 167,277 | 953,700 | 1,063 / 978 | 3,733 | 919 | 64 |

Each graph also contains one `crate_for_resolver`, one `resolver_for_lowering_raw`, one `analysis_interfaces` and one `analysis` node. Each has zero recorded outgoing edges. Their declarations use `eval_always`. The saved root table contains only the typeck and borrowck roots above. Replaying just those roots misses work performed by the resolver. A query's stored result fingerprint for a type or signature uses a different representation from a metadata row's aggregate public fingerprint. Establishing equality requires comparable type or signature inputs. Many external providers currently read the complete external metadata input hash, or the private crate hash where required. Force-running a current provider or conservatively invalidating a changed whole-crate input can handle those reads. [Query declarations](https://github.com/astral-experiments/ohm-rust/blob/d57fd1515986dccecdcece8da85e651bfb4b81f9/compiler/rustc_middle/src/queries.rs), [external provider dependency](https://github.com/astral-experiments/ohm-rust/blob/d57fd1515986dccecdcece8da85e651bfb4b81f9/compiler/rustc_metadata/src/rmeta/decoder/cstore_impl.rs#L151-L166)

A real provider force currently runs under a current compiler type context. The ordinary driver creates that context with an already parsed crate and derives the crate name and crate types from its configured attributes. Moving this work ahead of parsing would require a new way to establish those current-session inputs. [Driver entry](https://github.com/astral-experiments/ohm-rust/blob/d57fd1515986dccecdcece8da85e651bfb4b81f9/compiler/rustc_interface/src/passes.rs#L1077-L1093), [previous-node force](https://github.com/astral-experiments/ohm-rust/blob/d57fd1515986dccecdcece8da85e651bfb4b81f9/compiler/rustc_middle/src/dep_graph/mod.rs#L103-L112)

## What a whole-graph scan can detect

Three four-crate Cargo fixtures used the source-built compiler from the Ruff qualification. Each was checked before the edit, unchanged, after the invalid edit, from an empty invalid target, after repair and from an independently empty repaired target. All three warm and clean diagnostic codes match. The producer and facade metadata for each invalid input agree byte-for-byte with their independent clean output. The repaired consumer agrees too. [Raw query decisions](query-controls.json), [constant and glob native stale-output reproductions](../indirect-check/README.md), [blanket-impl native originals](blanket.tar.xz)

* A reexported `$crate::VALUE` starts returning `&str` in a function that returns `u8`. The genuine E0308 has a previous `typeck_root` to `type_of(origin::VALUE)` edge. Neither changed definition's stable local ID appears in the old facade or consumer metadata.
* A glob import previously found a single `VALUE`. Adding a second `VALUE` raises E0659. The two old consumer roots cannot reach the newly relevant module. A scan of all 615 nodes finds the old module's `module_children` at sparse index 38. Comparing the complete current lookup result could reject this edit. Scanning only previous successful `VALUE` lookups would miss it.
* Adding `impl<T> Candidate for T {}` makes a previously unambiguous method call fail with E0034. Replacing the blanket impl with `impl Candidate for () {}` repairs it. The producer's global public hash stays equal. The encoded trait-impl group count changes from zero to one, the facade's public hash changes and the original consumer graph has both `trait_impls_of` and `blanket_trait_impls` for `Candidate`. Any narrower proof must account for the full affected selection universe, including newly applicable implementations. In this compiler, the encoded local-traits array is intentionally empty with public hashing enabled, even for a declared trait. [Trait table writer](https://github.com/astral-experiments/ohm-rust/blob/d57fd1515986dccecdcece8da85e651bfb4b81f9/compiler/rustc_metadata/src/rmeta/encoder.rs#L3260-L3276)

In the constant and glob cases, substituting the current origin hash in the saved consumer's 16-byte dependency header lets the physical compiler accept stale metadata. The unchanged original header produces E0460 against the new origin. Both ordinary Cargo checks issue the correct source error. Header rebinding needs an independent proof of the entire old verdict before it can be considered. [Six direct compiler loads](../indirect-check/README.md)

## Native macro eligibility on Ruff

The enrolled #28444 ordinary Cargo plan contains 337 units. The reachable native macro-target counts for the four compiler owners are 21 for `ruff_linter`, 23 for `ruff_graph`, 24 for `ruff_workspace` and 24 for `ruff_markdown`. The first three have direct macro targets. Markdown has zero direct macro targets. A conservative rule requiring zero native macro targets in the whole dependency closure admits zero of four. This inventory measures availability. Counting invocations and excluding a reexported macro in Markdown require separate evidence. [Original 4-compiler roster and source behavior](../README.md)

A separate signed −23 ordinary Ruff #27470 check actually ran 12 compilers. In the `ty_python_semantic` rustc process, `perf script` assigns 2,014 of 14,488 retired-user-instruction samples to the mapped `libsalsa_macros-1490b2847bcc7d8e.so` with build ID `6aa564f2863239fab2868eaf13622458794d8c9b`. This establishes a native execution for that real process. Which inputs Salsa reads is a separate question. The signed compiler handles the general risk by running native attribute and derive macros each time that Cargo actually invokes it. The prior C-FFI control changed a macro expansion across calls despite unchanged Rust inputs. [Original signed profile](https://github.com/astral-experiments/ohm/actions/runs/41573331247), [−23 option behavior](https://github.com/astral-experiments/ohm-rust/blob/d57fd1515986dccecdcece8da85e651bfb4b81f9/compiler/rustc_session/src/options.rs#L986-L990), [FFI readback](https://github.com/astral-experiments/ohm-rust/pull/244)

The positive query keys establish opportunities for ordinary incremental query reuse after the appropriate current inputs have been checked. None of these observations certifies an entire changed-hash Ruff check early enough to reuse and rebind its old metadata. The eligibility screen gives us no supported workload for a hardware speed comparison.

## Reopen

Run the following in this directory. Supply the two original signed indexed RSIC files and the immutable hosted ZIPs. `census.py` verifies each input's complete SHA, the `perf.data` SHA before and after decompression, the full graph counts, Cargo closure and original macro ELF build ID. `query_controls.py` reopens the three graph/metadata/native diagnostic receipts against the candidate's checked-out schema. [#28444 original](https://github.com/astral-experiments/ohm/actions/runs/41569845446), [#27470 original](https://github.com/astral-experiments/ohm/actions/runs/41573331247)

```sh
python3 -IB census.py --ast-graph /absolute/ast/original-wire.bin \
  --parser-graph /absolute/parser/original-wire.bin \
  --scope-zip /absolute/41569845446-original.zip \
  --perf-zip /absolute/41573331247.zip
python3 -IB query_controls.py --rust-source /absolute/source/a7fc5bc7
```
