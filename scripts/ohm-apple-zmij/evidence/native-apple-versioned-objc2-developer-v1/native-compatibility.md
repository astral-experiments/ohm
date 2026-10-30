# Versioned native-link advisory safety on Apple arm64

Both source-built Rust arms were compiled on macOS 15 APFS in QA commit d1430be7a21b94e068b92e0e8fe2ca5775588eb4. P′ is the CRC parent with the new native Apple marker. C′ adds the independently measured ObjC instruction recognizer. The three native Cargo receivers used the same paths, real Rust drivers and Apple libraries.

| Receiver | SHA-256 | Full registry rustcs per unchanged check | Other full rustcs | Link-only rustcs | Stock Xcode links |
| --- | --- | ---: | ---: | ---: | ---: |
| signed | 505008003127f597cf2bdbd967d2bac9158d706b55a18f8bf17790e9ea3bbac9 | 2 | 1 | 0 | 1 |
| classic | 15d606da92d473ecee01c2f8bf60afc3cd2c6948aa70b0a5043cd1095199ba81 | 2 | 1 | 0 | 1 |
| aware | ac37c705e1f523b7bd81f777c5897f835bd12b010b04fea3ef9ee5b7c33cc44c | 0 | 0 | 1 | 0 |

The independent registry reader used the Ruff-locked zmij 1.0.10 and zlib-rs 0.5.5, including its native AArch64 CRC routine. Every successful program printed `1.234 cbf43926`. All twelve actual readbacks matched their per-receiver independently empty complete native code and debug metadata under the registered, object-proven comparison. Both producers emitted the exact generated v2 prerequisite. The first and second unchanged observations directly agree.

The provider fixture used a real C archive returning 17 or 29, and real Rust changes returning 7, 11, 13, 15 and 19. Each of three receivers ran the 392-command parent/child matrix across direct and library placements, declared paths, genuinely unwatched archives, same-inode/size/mtime rewrites and missing/malformed/restored inputs. All required default, declared and Rust-edit results matched independently empty builds. The explicitly disabled unwatched cases reproduce conventional stale freshness and are retained. The two compatibility environments conservatively recompiled both real libraries. The receiver that recognizes v2 reused the returned reader only after its link-input receipt validation.

The same-target Cargo upgrade and downgrade test kept the compiler, Rust source pathname and working roots fixed in 72 genuine warm/empty commands. It covered signed→aware→signed and classic→aware→classic, both placements and valid, corrupt, removed and restored providers. A proc macro genuinely tracking either spelling remained a hard missing dependency across all three receivers. The aware Cargo attached an LNK1 receipt only when the v2 spelling was solely compiler generated. All 36 named-path commands and full original native readers passed.

The specific stored archive from [the Actions run](https://github.com/astral-experiments/ohm/actions/runs/41091420073/artifacts/12995107378) has SHA-256 `6f6ed9458077cd6c30d009b0364b12344124bff5d64964b46db921d4e6ac8577`, 116,085,028 bytes and 11,821 original files. From this directory, use the following commands to reread it without executing Cargo or rustc. Supply a BLAKE3 executable for the actual LNK1 trailer if it is outside PATH.

```sh
python3 -IB matrix.py apple-versioned-provider-and-migration.zip reopened
python3 -IB symbols.py apple-versioned-provider-and-migration.zip reopened --b3sum /path/to/b3sum
```

These are safety and mechanism observations. The separate foreground Ruff timing requires independent terminal native, pilot and confirmation stages.
