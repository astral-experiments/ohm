# What remains in the Ruff #27470 library test build

A full `ruff_db` test-crate rustc process spent 3.355 billion user instructions after all 216 of its previous native objects survived. The renderer’s compiler spent 1.953B and Wild spent 0.730B producing the changed final test executable. These are counts from one real edit with Rust #329 applied and signed Ohm −22 Cargo. They size further opportunities. The separate six-boot comparison measures the performance of #329. [Six-boot controls](../41442143564/README.md) · [Rust #329](https://github.com/astral-experiments/ohm-rust/pull/329)

The registered attribution job **failed its additional whole-rlib byte-equality check**. Before opening the Rust source-cost table, we separately qualified the profiled edit against an ordinary edit using complete producer metadata, native objects, Cargo freshness, and real outputs. The independently clean New renderer rlib has a different serialization. An earlier observer changed `PATH` and rebuilt all 171 Cargo units. The corrected observer restored the exact role environment, and both edited histories rebuilt only the renderer and consumer. [Original diagnostic run](https://github.com/astral-experiments/ohm/actions/runs/41449096152) · [Original diagnostic source](https://github.com/astral-experiments/ohm/blob/8147d48732966564bbe190edb6824d5e65d2ec59/scripts/ruff-heldout-mono-fold/RESIDUAL.md)

## Whole command

Ruff moved from `bb868838d75876c3b016d8cf1687d33eae80daa6` to `9c53b5de3aae4b1832eb7ee137647dda2466f888` at the same path. We used the matched source-built Rust compiler `259ad7069e47eaf08cf106f187b2b6393f7fd7c2`, Cargo −22, and Wild 0.11.0. The observers ran the ordinary Cargo command below. Actual libtests and the separately linked renderer client ran afterward. [Ruff edit](https://github.com/astral-sh/ruff/pull/27470) · [Compiler factory](https://github.com/astral-experiments/ohm/actions/runs/41431225435)

```sh
cargo +ohm test --no-run -p ruff_db --lib --locked --offline -j2 --message-format=json
```

| Process | Retired user instructions |
| --- | ---: |
| `rustc --test` for `ruff_db` | 3,354,985,140 |
| `rustc` for `annotate_snippets` | 1,953,247,699 |
| Wild | 729,563,826 |
| Cargo | 293,058,644 |
| Link drivers | 11,739,461 |
| Rustup | 9,847,446 |
| **Total** | **6,352,442,216** |

All 376 individually counted tasks had unmultiplexed hardware events. The disjoint sum equals the inherited command counter exactly. The ordinary unprofiled edit counted 6,354,113,252 instructions, a difference of 0.0263%. The task counters recorded another 129,141 instructions in the observer wrappers, outside the command total. The consumer ran a full compiler invocation, without `-Zlink-only`.

## Rust compiler samples

Linux produced 6,334 samples at a fixed period of 1,000,003 retired user instructions. An independent decoder matched every kernel-recorded process, thread, timestamp, period and instruction pointer to the symbolizer. No overflow records were lost or throttled. The 31 interrupts recorded with a kernel-mode leaf contribute to the process census and remain outside named user-space subsystems. Outside the two rustc processes, 728 samples came from Wild, 292 from Cargo, 11 from link drivers, nine from rustup and 16 from the observers. Each row below counts the sampled *leaf* once. Shared allocator, symbol, and span operations cannot be assigned to a calling phase on these frame-pointer stacks.

| Leaf category | Consumer `ruff_db` | Producer `annotate_snippets` |
| --- | ---: | ---: |
| Parse, expand, resolve and lower | 396 | 75 |
| Types, MIR and related queries | 249 | 196 |
| Previous-node green validation | 371 | 79 |
| Graph writing and coloring | 125 | 14 |
| Previous-graph indices | 83 | 21 |
| Decode previous graph | 55 | 11 |
| Other declared dep-graph code | 24 | 8 |
| Record reads by current queries | 21 | 72 |
| Query machinery and result storage | 212 | 157 |
| Crate metadata | 213 | 75 |
| LLVM library | 5 | 415 |
| Native link orchestration inside rustc | 1 | 0 |
| Spans, interned symbols and stable hashing | 515 | 192 |
| Named libc allocation or other libc functions | 157 | 111 |
| Unresolved libc | 186 | 131 |
| Unresolved dynamic loader | 28 | 22 |
| Other named compiler or runtime code | 684 | 350 |
| Kernel-mode leaf at interrupt | 16 | 8 |
| **All compiler samples** | **3,341** | **1,937** |

Green validation, graph writing, index lookup, decoding and other declared graph functions account for 791 samples across the two compilers. Across the original six hardware pairs, the median additional reduction needed to reach 2× against the parent was 726.85M instructions. That is approximately 92% of this broad sample group. The largest leaf, `try_mark_previous_green`, has 444 samples. In the matched driver, 262 of those resolve to the instruction immediately after a locked compare-exchange. They do not measure the removable cost of that single instruction. This trace establishes neither a new graph optimization nor a second performance result.

## What changed in the producer metadata

The renderer’s public crate hash changed from `0d3912fab66d14216bcfedb2a8f98bc7` to `2726ed763f927f0e0319231c080175e5`. Its physical metadata confirms two inputs changed.

* The number of truly exported generic symbols grew from **1,019 to 1,028**. This is the producer’s encoded `exported_generic_symbols` array. The compiler hashes it in the crate-global fields with reachability-edge recording disabled. The separately stored global fingerprint changed. [Pinned encoder](https://github.com/astral-experiments/ohm-rust/blob/259ad7069e47eaf08cf106f187b2b6393f7fd7c2/compiler/rustc_metadata/src/rmeta/encoder.rs#L3420-L3430)
* **771 of 1,099** stored local-definition fingerprints changed across the same stable definition identities. The crate root is an unconditional public graph root. Its own transitive fingerprint changed, and 415 definitions share that old/new fingerprint pair. This establishes a changed reachable graph input even if exported generic symbols were treated separately. The 771 are transitive results and may share a cause. The serialized table cannot apportion that cause between reachable source spans, MIR and the other metadata fields. [Graph roots](https://github.com/astral-experiments/ohm-rust/blob/259ad7069e47eaf08cf106f187b2b6393f7fd7c2/compiler/rustc_metadata/src/rmeta/encoder/public_api_hasher.rs#L784-L795) · [Separate global and reachable hash inputs](https://github.com/astral-experiments/ohm-rust/blob/259ad7069e47eaf08cf106f187b2b6393f7fd7c2/compiler/rustc_metadata/src/rmeta/encoder/public_api_hasher.rs#L613-L631)

The consumer’s five actual incremental graphs contain 1,487 distinct renderer-qualified `(kind, key)` pairs apiece. Of those, **1,485** match the producer’s stored public-definition identities, across 73 query kinds. Among these 1,485 pairs, **1,481 have equal nonzero result fingerprints**, one has equal zero, and three change. In 1,469 of the 1,485 pairs the producer’s transitive fingerprint changed at the underlying definition. Multiple query kinds can read the same definition. The three changed query results are `crate_hash`, `external_metadata_input_hash` and `exported_generic_symbols`. Hashing the actual producer private and public crate headers reproduces the consumer’s first two result fingerprints in both revisions. All 127 `type_of` pairs, 37 `fn_sig` pairs and 34 `def_ident_span` pairs have equal recorded results.

Exactly 1,210 renderer-qualified rows have a direct edge to the coarse `external_metadata_input_hash`. Within that group, 1,208 nonzero result fingerprints match, one result is zero and only `exported_generic_symbols` changes. No `extern_def_public_hash`, `extern_expn_public_hash` or `public_global_hash` query nodes appear in the five consumer graphs. The final consumer wrote a test executable and used `-Zpublic-api-hash=no`. The same source hashes, result inventories and direct-edge memberships reproduce in the independent histories. These observations cover the reads present in this build. They cannot authorize skipping absent queries, error handling, source locations or arbitrary future edits. [External metadata dependencies](https://github.com/astral-experiments/ohm-rust/blob/259ad7069e47eaf08cf106f187b2b6393f7fd7c2/compiler/rustc_metadata/src/rmeta/decoder/cstore_impl.rs#L152-L165)

## Why the original job refused

* Ordinary and sampled edits produced the same 171 Cargo artifacts and dirty set, exactly 123 admitted registry products, the same full 126-test inventory, and the expected verdicts in both selected tests and both native renderer cases. Both retained every pinned caller object. The independent clean test executable has the same SHA-256, `aa84b0d508890e24f77047e42e32d7f53e72c9e6d4e1b97d72e8d9a669d0ec2a`. Six of the renderer’s 118 native codegen units really changed on this edit.
* Each of five full rlib archives has its own SHA. Between the ordinary and sampled edit, full `lib.rmeta` bytes match, as do all 118 complete native bodies identified by stable CGU, all 3,199 allocated ELF sections and all 1,793 archive-symbol names, owners and offsets. Replacing exactly the seven-character session suffix in each native member name gives identical GNU filename and Rust `lib.rmeta-link` tables.
* Independently clean New has the same native bodies, full test ELF, rendered frames and matching compiler `-Zls=all` output, including public and private hashes. Its inner metadata is 442,211 bytes versus 442,333 warm. This reduces the enclosing ELF by 120 bytes and moves every native object and every archive-symbol offset back by 120 bytes. Its interpreter-allocation index has 179 entries versus 186 warm. All 1,099 stored local fingerprints and all 170 stored expansion fingerprints agree across the three New builds. The packet preserves all three distinct raw metadata sections.

## Reopen the evidence

From this checkout, run the offline reader with Python 3.11 or later and `zstd`. It checks the compact archive digest, counters, raw kernel PCs, source-vs-native controls, metadata tables and individual query witnesses.

```sh
python3 scripts/ruff-heldout-mono-fold/evidence/41449096152/verify.py
```

While GitHub retains the complete original, the same reader can independently verify every native body and rederive the 1,487 renderer rows, their direct marker edges and complete per-kind histograms from each physical consumer graph. This needs a temporary 148,377,764-byte download. The compact archive is 1,406,737 bytes, SHA-256 `d5a6fdacd47cab931ebf17f75d7a7d8e50c1b1beb2ec9dd322c78a88689ddbdb`.

```sh
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13143119648/zip > /tmp/ruff-27470-residual.zip
python3 scripts/ruff-heldout-mono-fold/evidence/41449096152/verify.py --original /tmp/ruff-27470-residual.zip
```
