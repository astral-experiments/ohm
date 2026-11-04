# Restoring interned CTFE allocations fixes two ordinary Rust metadata histories

The published #318 implementation was ported onto the exact Ohm 1.99.0-24 Rust source. It preserves the identity of the compiler’s own previously interned, immutable, salt-zero allocation when the same allocation returns from incremental storage. The qualification translates the PR’s incremental-format bump to the release branch’s numbering, 57124 → 56167. Matched stage1 compilers shared the release Cargo and Wild. The separately tested port uses Rust `93bf5c0a94d75e39c45fc3009da2c239bb5976af`, directly after `f5a51d8cc3e76236c2d0f17d495d59ebb03306e4`. [Existing Rust PR](https://github.com/astral-experiments/ohm-rust/pull/318) · [Exact release-source port and factory](https://github.com/astral-experiments/ohm/actions/runs/41748724559)

Ruff #26372 added `--extend-exclude` to `ruff format`. Each role first built an ordinary consumer at OLD, changed only the real producer to NEW, rejected a type error twice, repaired it, then restored the identical original producer source. The next ordinary commands were `cargo +ohm build -p ruff --bin ruff` and, separately, `cargo +ohm build -p ruff_dev --bin ruff_dev`. Both selected the genuine library from the consumer rustc’s `--extern` and ran typed probes against it. The two unit graphs selected different dependency features. [Normal matched Ruff workers](https://github.com/astral-experiments/ohm/actions/runs/41750196339)

| Original versus restored producer | F5 parent | F5 + #318 |
|---|---:|---:|
| Raw allocation records, both consumers | 214 → 232 | 214 → 214 |
| Changed public fingerprints, both consumers | 1,098 / 1,671 | 0 / 1,671 |
| Whole original and restored .rmeta identical | 0 / 2 | 2 / 2 |
| Unchanged Rust definitions and expansion rows | 3,027 and 391 | 3,027 and 391 |
| Unchanged required crate hashes | 288 / 291 by feature set | 288 / 291 by feature set |

**Both arms ran the same full downstream rustcs.** The standalone Ruff build ran its binary compiler. The other build ran `ty_python_semantic`, the `ty` library and `ruff_dev`. The four unchanged controls in each history independently reproduced the ordinary floor, zero compiler processes for Ruff and one full `ty_python_semantic` plus one link-only `ruff_dev` for the other target. The unchanged downstreams had last built against OLD, while the immediate previous producer had built the genuinely different NEW interface. The candidate’s public fingerprint changed at both OLD → NEW and NEW → OLD. Cargo compares the immediately preceding producer publication before it restores a metadata timestamp. The collector retained zero direct Cargo-dirty fingerprint files for these historical paths, so it cannot assign an exclusive reason for each job. This experiment supplies no whole-workflow speed estimate. [Exact Cargo comparison](https://github.com/astral-experiments/ohm-cargo/blob/abc70d60a6fd89c10d5f65cf85820d9b78d5affe/src/compiler/fingerprint/mod.rs#L1135-L1198)

All physical Ruff object members matched across restoration after pairing the actual archive member names by their compilation nonce. The candidate had 215 members in Ruff and 209 in the other library selection. Both raw archives changed with the nonce and the `.rmeta-link` wrapper. The actual linker symbol maps and normalized wrappers matched. The two authentic originals yielded six distinct full executable bodies. Restored programs matched their initial bodies, and each fully edited Ruff CLI matched its independently empty NEW build. The changed `FormatCommand` field was usable at NEW and rejected with E0609 at OLD. The real old CLI rejected the new flag, and the edited CLI formatted only the expected file.

## Unicode and pointer controls

A separate historical Ruff edit changed two Unicode-generator sources. Its ordinary Cargo check had 20 nonfresh units at OLD, three at the edit, zero on the unchanged check, and 20 at each of two independently empty NEW builds. On signed -24 and the matched F5 parent, incremental NEW had two extra string allocations for `BS` and `GS`, producing 555 records versus 553 and a metadata file 26 bytes longer. The port had 553 records in each case. The complete edited metadata, unchanged repeat and two independently fresh outputs were byte-identical. The native downstream changed all five expected Unicode lookups, retained both controls, and had identical complete ELF bytes at edited, unchanged and clean NEW. [Unicode source change](https://github.com/astral-sh/ruff/compare/26911caa2800758779965510d2f222b438abbb38...276832aa91f2086a6ec880884fcdd987991cddf2)

Two-crate pointer controls distinguished shared from distinct equal-byte statics, an offset pointer, increased alignment, and a mutable static. The five cases retained five distinct public fingerprints. Anonymous promotions, E0308 twice and a repair ran as separate cases. The additional CTFE fixture evaluated pointer equality in the consuming crate and checked the indeterminate case for separately promoted storage. All seven valid histories preserved their own clean executable and native result.

## Reproduce the readback

The Linux readers require Python 3.11+ and `zstd`. From the packaging root:

```sh
folder=scripts/ruff-clap-reverse-metadata/evidence-ctfe318-rc24
python3 -IB "$folder/replay.py"
python3 -IB "$folder/companion.py" --run-native
```

`physical-probes-and-metadata.zip` retains the marginal raw kernel image streams, selected metadata, member inventories, diagnostic payloads and real CLI behavior. The compact reader checks those directly. The 5.3 MB Unicode packet includes complete raw metadata and both actual downstream ELF bodies, which `--run-native` executes after authenticating the entire packet.

For the independent readback of every original CLI ELF and both cold process inventories, download Actions artifacts 13285899382 and 13285864758 as `P.zip` and `C.zip`. Run `python3 -IB "$folder/verify.py" DIRECTORY` to verify their complete SHA-256 and compare the result to `verified.json`. The retained kernel streams include their original exit codes. This study uses those streams for process and verdict verification.
