# Two remaining workspace codegen units after Rust #329

On six independently initialized Ruff #28335 builds, the source parent retained **83 of 124** ruff_workspace objects. The candidate retained **122 of 124**. Its 42 additional donors across the build came from 39 in this crate and three in ruff_linter. The earlier signed compiler regenerated 49 workspace objects. Subtracting the whole-workload gain from that earlier count mixes compiler populations and crates. [Six-boot original and independent reader](https://github.com/astral-experiments/ohm/blob/d1ecf880bf5b846ca0d684f27cdbd9c0c6d1d47a/scripts/ruff-upstream-mono-confirm-reader/results/41433784058/README.md), [Rust #329](https://github.com/astral-experiments/ohm-rust/pull/329)

| Actual candidate object | Rust module | Candidate OLD → edited object | Matching signed object |
|---|---|---|---|
| `bkqk9vgkyoct0gf3jem7b0j8g.o` | `serde::private::de::content`, volatile | New inode, identical SHA-256, 1,734,056 bytes | `1ik705odb0wi7ez86mr5nie6x.o` |
| `bovx324z7crw0xpikj5eolqyd.o` | `core::iter::adapters::map`, volatile | New inode, changed SHA-256 | `app6md24z3cxw0zevcj31kxdh.o` |

All six candidate histories agree. The Serde unit is the only remaining byte-identical result. The second unit's signed original already has a changed symbol/relocation witness. We recovered the two compilers’ different stable crate IDs from their actual incremental directory names and independently reconstructed rustc’s 128-bit filenames. The reader reproduces 122 of 124 names in each population, including both regenerated units and all nine previously disputed units. The two unjoined candidate names were physical donors. Eight of the nine signed unforceable units with unchanged direct inputs were candidate donors. The reconstruction includes the second hash that rustc applies to numbered shards. [Crate directory identity](https://github.com/astral-experiments/ohm-rust/blob/259ad7069e47eaf08cf106f187b2b6393f7fd7c2/compiler/rustc_incremental/src/persist/fs.rs#L596-L601), [CGU name builder](https://github.com/astral-experiments/ohm-rust/blob/259ad7069e47eaf08cf106f187b2b6393f7fd7c2/compiler/rustc_middle/src/mono.rs#L665-L744), [numbered shards](https://github.com/astral-experiments/ohm-rust/blob/259ad7069e47eaf08cf106f187b2b6393f7fd7c2/compiler/rustc_monomorphize/src/partitioning.rs#L373-L384)

## The signed Serde compiler reached a changed trait input

Signed −22’s actual callback followed this chain. The direct layout, normalized generic argument and canonical projection all had unique, equal old and current result fingerprints. The full trait implementation query changed. Its anonymous selection parent was absent from the current graph. The final attempt to force layout failed. This was the sole direct layout rejection in the 49 signed misses. Nineteen stopped at an ABI query, 16 at a symbol name, 12 at the old upstream-mono query and one at codegen_unit. [Original signed callback](https://github.com/astral-experiments/ohm/actions/runs/41417607187), [all typed rows and original sparse indices](receipt.json)

```text
CompileCodegenUnit
  layout_of
    try_normalize_generic_arg_after_erasing_regions
      normalize_canonicalized_projection
        TraitSelect
          trait_impls_of(core::iter::traits::collect::IntoIterator)
```

The signed core metadata identifies the trait declaration, `IntoIterator::IntoIter` and the selected `core::slice::iter::{impl#1}::IntoIter`. The pinned Rust source implements that item for a mutable slice and defines its output as `IterMut<'a, T>`. The observed projection requires generic arguments, including an element type. The associated-type DefId alone cannot reconstruct the full input and its typing environment. The existing graph records the stable key and results. The actual element type remains unknown. [Signed core implementation](https://github.com/astral-experiments/ohm-rust/blob/008a21ac0d750dc9a1c18b7959d7e7984c03d887/library/core/src/slice/iter.rs#L17-L33), [layout normalization](https://github.com/astral-experiments/ohm-rust/blob/008a21ac0d750dc9a1c18b7959d7e7984c03d887/compiler/rustc_ty_utils/src/layout.rs#L62-L98), [real external blanket-implementation addition and E0034](../ruff-linter-check-attribution/evidence/field-visibility/preflight/README.md)

Exactly one of the trait query’s 306 direct inputs changed result, `implementations_of_trait((ruff_python_ast, IntoIterator))`. The reader reconstructs this tuple from the signed crate’s directory and the signed core’s actual trait identity, plus seven independently observed crate lookups under the same encoding. All 247 per-crate trait-membership keys remained equal. The original data do not identify which implementation-list entry moved. Eight signed rejected CGUs encountered the same changed trait input. Seven were donors in the matched candidate. Earlier work already covers per-crate trait filtering and public-metadata tracking of private concrete impls. [Rust #222](https://github.com/astral-experiments/ohm-rust/pull/222), [Rust #232](https://github.com/astral-experiments/ohm-rust/pull/232)

## Instruction opportunity

Reopening all 353,231 raw retired-user-instruction samples reproduced the enrolled worker table. The Serde worker owned an estimated **9,106,013,659 instructions** at a period of 2,000,003. The signed ruff_workspace rustc retired 76,519,485,000 instructions. Its enclosing ordinary `cargo build -p ruff --bin ruff` retired 707,687,555,161. Giving a perfect skip the entire sampled worker yields **11.90% of that rustc or 1.29% of that build**. This study captured the workspace compiler as a child of the Ruff build. A standalone `cargo build -p ruff_workspace --lib` has no measurement in the enrolled histories. [Signed hardware original](https://github.com/astral-experiments/ohm/actions/runs/41357296901), [signed native originals](https://github.com/astral-experiments/ohm/actions/runs/41362345812)

The matched #329 ledgers establish current byte identity and donor decisions. They contain neither a per-CGU instruction count nor a first-rejected-edge callback for the candidate. Its precise cause and cost remain open. The signed opportunity alone does not warrant an invasive query redesign. The other, genuinely changed unit remains outside this candidate, including source-coordinate work under Rust #340. [Matched source confirmation](https://github.com/astral-experiments/ohm/actions/runs/41433784058), [Rust #340](https://github.com/astral-experiments/ohm-rust/pull/340)

## Reopen

The 199 KB compressed packet retains all 12 parent/candidate native ledgers, the original signed callbacks and prior donor inventory, and the signed instruction and direct-edge records. The reader verifies every included member, every reported name across both compiler populations, the inodes and SHA-256 in all six pairs, and the signed instruction arithmetic. Use the optional original RSIC graphs and core metadata to independently verify the changed edge, all 305 stable siblings, and the trait and impl identities.

```sh
python3 -IB scripts/ruff-329-layout-residual/verify.py
python3 -IB scripts/ruff-329-layout-residual/verify.py \
  --old-graph /absolute/c61bb34d8fba3f5cff19de4475340179d783adc976455ea3fe94d92356bf0c77.gz \
  --new-graph /absolute/54c33c1062b889240d8f118dae43c4a40da51f5f9732b4381b2c5c51e0f30bce.gz \
  --signed-core /absolute/signed-22/lib/rustlib/x86_64-unknown-linux-gnu/lib/libcore-af9b82d80b4c5cea.rmeta \
  --rust-source /absolute/ohm-rust-a7fc5bc7
```
