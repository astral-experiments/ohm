# Two original Ruff edits retained all six selected downstream checks

Both compiler versions ran all three selected downstream rustcs in each history, in both edit directions. Neither workload qualified for hardware counters. This was a single structural worker, with zero scored pairs.

| Ordinary Cargo check | Physical rustcs on parent / candidate after edit | Producer definition fingerprints changed on each | Settled repeat |
|---|---:|---:|---:|
| Ruff CRLF line-end fix, checking the Python literal library | 4 / 4 | 347 of 626 in `ruff_source_file` | 0 / 0 |
| Ruff loose Unicode name-matching revert, checking all examples | 6 / 6 | 65 of 81 in `unicode_names2` | 0 / 0 |

The exact same stable definitions changed on parent and candidate. The candidate's actual producer argv contained `-Zohm-checked-private-derives-v2` in both histories. The parent argv omitted it. Both used the same physically verified Cargo. The original scope, compiler driver digests, two Git commits per history and lockfiles are in the [registration](../plan.json). [Structural worker](https://github.com/astral-experiments/ohm/actions/runs/41662416586) · [Matched P3/Q3 factory](https://github.com/astral-experiments/ohm/actions/runs/41621745224)

* **LineIndex.** The producer, `ruff_python_trivia`, `ruff_python_ast` and `ruff_python_literal` all ran. The producer changed its public hash and 347 existing rows, including `line_end_exclusive`, `IndexKind`, its two variants, and `OneIndexed`. The three consumers retained all their own public rows and public header. Their stored required-input rows each changed for `ruff_source_file`. All 54 recorded non-workspace artifact bodies and both generated bodies stayed identical through the ordinary edit and the independent empty check. [Ruff change](https://github.com/astral-sh/ruff/commit/88d851449d2345e11da991794f3e9bfbbd666719)
* **Unicode.** The generator, build script, library, and genuine examples `character`, `count` and `name` all ran. The producer's public hash and 65 existing rows changed, including `Name_`, its variants, and `character`. Its build script changed the contents of `generated.rs` and `generated_phf.rs`. All 37 recorded external artifact bodies stayed identical in the same arm. The observed graphs contain zero GetSize products. [Ruff change](https://github.com/astral-sh/ruff/commit/88a50d695c1142294bb4c780fad47d3306173885)

The source check, reverse, type error, repair and independently empty check were acquired separately from the native builds. All four injected producer errors reported E0308. On the CRLF input the linked LineIndex reader changed its end offset from 2 to 1, with LF and final-line offsets both remaining 1. The actual Unicode example accepted the canonical name in both revisions and rejected the loose spelling only after the revert. The complete native ELFs matched the independently empty edited build, the restored old build and the corresponding other compiler in both histories.

All selected producer metadata matched the independently empty same-source build byte for byte. The LineIndex downstream `ruff_python_ast` output had a small same-source difference. On parent, 194 of 3,810,475 bytes moved among six synthetic opaque lifetime definition indices; on candidate, 128 among four. The reader accounts for every differing byte in forward tables, reverse lookup, keys, and resolved spans. All 17,037 public rows, 2,161 expansions, 40 dependencies, and crate hashes agree. The original-versus-restored controls have four and three such index moves, respectively. Each raw body is retained. The registered structural endpoint still has zero saved consumers.

## Reopen the exact worker

`ordinary.zip` is the original 22,890,776-byte hosted artifact 13242828250, containing 434 entries. SHA-256 is `ccb29ed41fa4de6b412439fb7fda071ebc4e82c25440bca69964090fdc8ae3c1`. The reader checks all 408 physically launched rustcs across 32 check commands, their loaded role-specific driver and every retained metadata body, verifies four native ELF bodies across 16 builds, and runs all 16 native consumer checks again. Python 3.11+, zstd, and a compatible x86-64 GNU/Linux host are required for this last execution.

From the root of this packaging checkout run:

```sh
study=scripts/ruff-private-enum-neighbors
proof=$study/evidence-41662416586
python3 -IB "$study/reopen.py" "$proof/ordinary.zip" \
  --sha256 ccb29ed41fa4de6b412439fb7fda071ebc4e82c25440bca69964090fdc8ae3c1 \
  --execute-native --output /tmp/ohm-private-enum-neighbors.json
gzip -dc "$proof/independent.json.gz" | cmp - /tmp/ohm-private-enum-neighbors.json
```
