# An identical Ruff source produced 1,098 different public fingerprints

On published Ohm 1.99.0-24, rebuilding the Ruff library at its original source after a real edit made two unchanged programs run additional compilers. With the producer already restored, the Ruff binary ran one full rustc. The separate `ruff_dev` build ran full rustc for the ty library and for itself. Before the edit and on the following unchanged visit, Ruff had zero compiler processes. The usual `ruff_dev` work was a full `ty_python_semantic` rustc and a link-only `ruff_dev` rustc. The final executable in each history matched its own initial executable byte for byte.

The edit adds `--extend-exclude` to `ruff format`. Each ordinary Cargo history built the original source, edited source, and restored source and checked a real typed client and executable. An independently observed history also collected the compiler's final metadata dependency graph. The three histories include two dependency feature selections. [Source edit](https://github.com/astral-sh/ruff/compare/03f787e51e94999977b9a5a32b0153d82d7e2142...fa4a7bca2db70229710892c97b26ea6fb046cfc4) · [First ordinary run](https://github.com/astral-experiments/ohm/actions/runs/41736319575) · [Second ordinary consumer and graph observer](https://github.com/astral-experiments/ohm/actions/runs/41742070846)

| Original source versus restored identical source | Result |
|---|---:|
| Stable definition identities and indices | 3,027 identical |
| Published per-definition rows | 1,098 changed of 1,671 |
| Expansion rows and required crate hashes | 391 expansions, 288 requirements for Ruff and 291 for the ruff_dev feature set, all identical |
| Final metadata graph nodes | 16,351 → 16,369 |
| Serialized allocation records | 214 → 232 |
| Changed rows after removing the 18 repeated leaf contributions in an offline graph calculation | 0 of 1,671 |

All 18 additions are second instances of existing immutable, byte-aligned memory strings without provenance. They include `Check`, `Format`, `exclude`, `line_length` and `target_version`. Every added group has the same physical registration caller, the signed compiler’s `encode_alloc_id` site at relative PC `0x600e6b6`. The final graph preserved all unique stable identities. The verifier decodes every one of the 209 original and 227 restored Memory records, both provenance edges and all four named static records in each history. The sole vtable’s encoded type-abbreviation offset also moved by 30 bytes. Its preceding discriminant, trailing trait bytes, and 208 bytes at the referenced type location match.

The reader walks the strongly connected components and counts each duplicated leaf’s contribution to every published definition. The 1,671 definitions fall into 25 coefficient vectors. Within each group the actual 128-bit published fingerprint has exactly one numerical old-to-restored delta modulo 2¹²⁸. All 1,671 deltas, including the 1,098 nonzero values, agree across the three independent histories. The full final topology and signed public rows are primary. Some upstream operations were inlined in the signed driver and could not be captured individually.

Existing [Ohm Rust #318](https://github.com/astral-experiments/ohm-rust/pull/318) preserves the compiler interner’s identity on restoration for a narrowly checked class of memory allocations. The offline calculation measures the effect of these repeated leaves. Any production treatment must preserve the observable differences between distinct named statics, pointer offsets, alignment, mutability, and shared or separate allocations.

## Reproduce

From the packaging repository root, run with Python 3.11+, `zstd`, and `c++filt` installed.

```sh
python3 -IB scripts/ruff-clap-reverse-metadata/evidence-signed-allocation-identity/verify.py
```

`public-graph-and-metadata.zip` contains the six original compressed metadata files, the final graph topology and stable IDs, the observed registration counts, and the unchanged consumer process and native-output receipts. `verified.json` is the deterministic output. To recreate the compact packet from the two original Actions archives, run `make_packet.py FIRST.zip SECOND.zip NEW-OUTPUT.zip`. It verifies each original's complete SHA-256 before projecting the 86 members.
