# Which Ruff dependency keys can rustc recover from an item?

The two independent cold `ruff_workspace` compilers identified all 30 sampled stable keys. Each key has exactly one named row in each cold graph. All 60 output fingerprints match the corresponding row of the original graph at the same Ruff revision. The 49 original codegen-unit decisions were selected from a trace that missed 75 inherited file descriptors and failed admission. A fresh worker later preserved all 326 original descriptors and reproduced every codegen-unit assignment, stable key, and prior and current output value. [Signed dictionary run](https://github.com/astral-experiments/ohm/actions/runs/41418298879) · [Original selection run](https://github.com/astral-experiments/ohm/actions/runs/41414492188) · [Admitted replication](https://github.com/astral-experiments/ohm/actions/runs/41417607187)

## ABI and symbol inputs

| Actual compiler input | Distinct keys | Codegen-unit occurrences |
| --- | ---: | ---: |
| Ordinary item with empty substitutions | 2 | 3 |
| Ordinary item with only an erased lifetime | 1 | 4 |
| Item with concrete type or const substitutions | 17 | 27 |
| Drop glue for `globset::Candidate<'_>` | 1 | 1 |
| Total | 21 | 35 |

All 21 contain a foreign definition from the perspective of the `ruff_workspace` rustc. A scan limited to local definitions covers zero of the 35 occurrences. Given the right foreign DefId, `Instance::mono` can construct seven of the inputs. Rustc erases each lifetime and explicitly rejects a type or const parameter in that constructor. Recovering the complete key also requires knowing that the ABI used the neutral codegen environment and an empty extra-argument list, both present in all 11 actual ABI keys. The standard opaque fingerprint supplies no inverse DefId lookup. [Signed instance constructor](https://github.com/astral-experiments/ohm-rust/blob/008a21ac0d750dc9a1c18b7959d7e7984c03d887/compiler/rustc_middle/src/ty/instance.rs#L517-L529) · [Signed default key recovery](https://github.com/astral-experiments/ohm-rust/blob/008a21ac0d750dc9a1c18b7959d7e7984c03d887/compiler/rustc_middle/src/dep_graph/dep_node_key.rs#L32-L54)

- Ruff’s `<LineLength as TryFrom<u16>>::try_from` accounts for one occurrence. Matchit 0.9.2’s `<UnescapedRoute as Deref>::deref` accounts for two. The latter crate’s other deref receiver, `UnescapedRef<'a>`, has a lifetime parameter absent from the selected input. [Pinned Ruff source](https://github.com/astral-sh/ruff/blob/b5dba861cc38e3f7fb4524c9ceba3e01a474ea13/crates/ruff_linter/src/line_width.rs#L135-L143)
- TOML 1.1.4’s `<MapDeserializer as serde_core::de::MapAccess>::size_hint` accounts for four. The original spelling has exactly one erased lifetime. This concrete TOML-owned method occurs in every corresponding unoptimized codegen unit. Its sequence-deserializer counterpart only occurs in part of the set. [Independent original codegen units](https://github.com/astral-experiments/ohm/actions/runs/41362345812)
- All 16 symbol-name occurrences have concrete type or const substitutions. Five are `Iterator::eq` instantiated for two reversed path-component iterators and three are cloning `Vec<u8>`. Seven distinct `<&T as Debug>::fmt` inputs include `Range<usize>`, `IntErrorKind`, `&str`, `OsString`, `Path`, `()`, and Ruff’s `ImportSection`. Each is independently visible in the matching codegen unit’s mangled symbols. The remaining symbol formats a vector of strings.

The other nine distinct identities are seven upstream-monomorphization definitions (12 occurrences), one layout, and one codegen unit. All seven upstream-monomorphization values changed between revisions. The layout is the `IntoIterator::IntoIter` associated type for a borrowed slice of Serde’s private `Content<'_>`. Its value stayed equal. All 30 sparse indices changed between the original revisions, so the join used the full dependency kind and 128-bit key. A reuse experiment would still have to validate the remaining ordered dependencies of each codegen unit.

## Admitted replication

An independent reader authenticated the entire 700,154,273-byte trace artifact, both original graphs, the work-products table, compiler arguments and inherited descriptor state. It reopened all 124 codegen-unit decisions and every original saved-object entry. Rustc marked 75 units green, found 36 unforceable inputs and recorded 13 units with an already-red input. All 49 terminal (codegen unit, reason, kind, stable key, prior value, current value) records matched the registered selection exactly, as did all 1,426 context pairs. The complete archive SHA-256 is `39f0cc2151dbfd7825e60097c77a9cc9a53d5b4393dce69a6e41ce00287b7ec8`. [Accepted original artifact](https://github.com/astral-experiments/ohm/actions/runs/41417607187/artifacts/13129072831)

## Controls and replay

Both full builds used GNU Ohm -22, the same 505 locked dependency archives, and the 375-unit CLI graph at the pinned A and B revisions. The query-key profiler ran only in the actual `ruff_workspace` library compiler. The reader checked both SHA-256 layers, the PID and the entire recorded argv. Four swapped graph/profile inputs were rejected. Of 1,396 additional context keys, 1,286 have a name in both cold builds. The other 110 have no name in either. The records retain every observed sparse index, value, raw query key string and source graph digest. [Signed profile recording code](https://github.com/astral-experiments/ohm-rust/blob/008a21ac0d750dc9a1c18b7959d7e7984c03d887/compiler/rustc_query_impl/src/self_profile.rs#L184-L246)

Compared with an earlier admitted, unprofiled signed build, the profiling wrapper changed one output path, 229 dependency search paths, 35 external crate paths, and one native search path in each 621-argument compiler invocation. Every extern kept its name and file basename. The crate disambiguator and dependency-graph command-line fingerprint agree. Both full CLIs have identical executable sections and executable load segments versus the unprofiled build, and the entire typed readers match. The full CLIs differ by 16 bytes in size. The only sections with different contents are debug info, debug macros, debug strings, and the GNU build ID. The CLI cases, typed 64/56-byte layout results, and contradictory E0308 diagnostics all passed. No timings or hardware counters were collected.

The original ZIP digests are `ebe6cc7f19056420c346b6c76d98924af151dec4652faa89853548026dc7515f` for the dictionary and `7fcb79b03d1e9abb61946d59e70fa369a88a349f743a07683680de47fbb0ef9b` for the independent unprofiled codegen units. [Dictionary artifact](https://github.com/astral-experiments/ohm/actions/runs/41418298879/artifacts/13128672389) · [Unprofiled artifact](https://github.com/astral-experiments/ohm/actions/runs/41362345812/artifacts/13105414337)

To validate the compact registered result:

```sh
python3 -IB scripts/ruff-query-dictionary/check_result.py
```

To independently reopen the two complete original profiles, compare executable segments, and verify the selected mangled declarations from physical LLVM bitcode, extract the dictionary ZIP and pass the original unprofiled ZIP intact:

```sh
python3 -IB scripts/ruff-query-dictionary/check_result.py /path/to/dictionary \
  --unprofiled-artifact /path/to/41362345812-13105414337.zip \
  --admitted-trace /path/to/41417607187-13129072831.zip \
  --llvm-dis /path/to/llvm-22/bin/llvm-dis
```
