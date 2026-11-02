# One moved diagnostic span stopped 49 green checks in uv-client

After [uv #21041](https://github.com/astral-sh/uv/pull/21041), 28 type checks and 21 borrow checks on 31 definitions all encountered the same first failed incremental read. The generated-derive compiler had retained the implementation inventory for `rkyv::Archive` on `HashDigests`. Rustc then read the implementation’s `clauses_of` result and found its fingerprint had changed.

The single requirement in that result was identical across the original build, edited build and independent clean build.

```rust
Box<[uv_pypi_types::simple_json::HashDigest], alloc::alloc::Global>: rkyv::Archive
```

The diagnostic span refers to the 13-byte token `rkyv::Archive`. It moved from line 736, column 5 to line 776, column 5 in `crates/uv-pypi-types/src/simple_json.rs`. Its start moved 677 bytes. The source slice, stable expansion hash, complete hygiene chain and defining procedural macro were the same. We decoded every predicate and type shorthand, normalized every DefId and compared the complete encoded ADT data for `Box`, `HashDigest` and `Global`, including fields, variants, visibility, flags, representation and hash seeds. The parent, bound variables and inferred outlives clauses were all empty.

## What the native compiler did

A separate debugger replay of the terminal compiler from the ordinary `cargo check -p uv-client --locked --offline -j8` used a fresh private copy of its real A incremental state. The eight Cargo compiler commands, all 37 A and B metadata products and all 58 terminal externs were verified first. The observed process used the original 983 kernel arguments, compiler, sysroot, ELF and verified A seed. Its outputs, diagnostic JSON and raw B dependency graph reproduced the earlier unobserved native run exactly. The source for all 377 machine instructions in the previous green-mark walk matched the candidate at opcode/register/branch level. The ELF relocation resolution and actual three breakpoint bytes were verified independently. The original request and all 20,830 mark-failure records are compressed alongside this file.

The exact foreign key was `0a58e206df8989e90cf29d2dd0d07db6`. The native A result fingerprint was `5eaf4170c68906b76a1fbec21e7ef780` and B was `cbaf71318760fc60c0c70bc0b20c4854`. Event 1278 was a successful force that marked the key red. On all 49 later first-failure paths the runtime found that same physical key already red. The result matched `explicit_clauses_of` in each graph. The other two direct queries, `inferred_outlives_of` and `def_kind`, kept their positive results. Neither Archive bucket nor the blanket Deserialize bucket appeared as a failed child in the capture.

| Immediate reader of the shared failed key | Previous native node | Owners whose first failure followed it | Actual B graph |
| --- | ---: | ---: | --- |
| `TraitSelect` | 41568 | 41 | Missing |
| `TraitSelect` | 45397 | 6 | Missing |
| `normalize_canonicalized_projection` | 245998 | 1 | Present with the same positive result |
| `normalize_canonicalized_projection` | 248283 | 1 | Present with the same positive result |

All 49 root keys remained present with equal positive result fingerprints after executing. The detailed record classifies every physical hop by its real return reason, previous key, ordinary B presence and fingerprint. For every root it also records any other changed, absent, zero or ambiguous direct input.

## How much earlier work was exposed

| Cohort of previously paid providers | Count | Earlier parent hold 1, guest instructions | Earlier parent hold 2, guest instructions |
| --- | ---: | ---: | ---: |
| Entire shared first-failure cohort | 49 | 594,096,860 | 593,652,530 |
| Also read a different, positively changed direct result | 10 | 169,980,618 | 170,229,736 |
| Remaining after excluding those 10 | 39 | 424,116,242 | 423,422,794 |

The last two rows partition the first row. These are original disjoint parent provider intervals. They establish the observed cost of the exposed work. Recoverable work on the candidate requires a new measurement. Every root also had at least one zero-valued direct input and 26 had at least one prior direct input absent from B.

This gives a focused compiler experiment. An impl-confirmation path that needs the bound can depend on its semantic terms while obtaining its current precise location when producing a diagnostic. A regression should move a real bound and check the warm error’s updated source range, then change the bound’s type or polarity and check that warm and clean compiles agree. The fixed source and native diagnostic make no standalone speedup claim.

## Replay

Run `sha256sum --check --strict SHA256SUMS` in this directory, followed by `python3 -ISB replay.py`. Both commands use only the compact packet. With the original installed SDK and histories available, `python3 -ISB validate-clauses.py` reopens the three genuine metadata products and both native graphs. Seven deliberate adversarial alterations include a changed ADT seed with all identifiers retained and a moved location with the entire bound unchanged. Exact compiler source blobs are in `clause-validation.json`. No compiler is launched by these replay commands.
