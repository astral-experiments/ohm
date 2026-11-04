# Ruff CLI help edit on six fresh Linux boots

Changing Ruff’s generated `--config` help example from `lint.line-length = 100` to `line-length = 100` took **36.94% fewer retired user instructions** for the complete `cargo +ohm build -p ruff --bin ruff`. Both matched compilers built the unmodified commits from [Ruff #28392](https://github.com/astral-sh/ruff/pull/28392). Every paired reduction lies between 36.934% and 36.966%. This is the exact distribution-free 96.875% interval for the median of six independent pairs, with two-sided sign-test p = 0.03125. The separately observed full Ruff library rustc used 45.23% fewer instructions (45.17–45.27%).

| Fresh machine | Order | Parent, all user instructions | Candidate, all user instructions |
|---:|:---:|---:|---:|
| 0 | PC | 20,142,801,103 | 12,696,799,953 |
| 1 | CP | 20,130,644,657 | 12,695,003,267 |
| 2 | CP | 20,136,946,083 | 12,696,015,001 |
| 3 | PC | 20,133,310,015 | 12,697,348,656 |
| 4 | PC | 20,132,874,788 | 12,696,597,177 |
| 5 | CP | 20,140,422,579 | 12,697,224,824 |

The stock source is `f5a51d8cc3e76236c2d0f17d495d59ebb03306e4` from the released `-24`. The candidate is `025c787a77f5d887ba9bf860ef69b7756b59fe57`. These are matched stage1 builds with LTO off, the same bootstrap source and arguments, and the same signed Cargo and Wild binaries. Published `-24` used stage2 with native PGO, ThinLTO and BOLT. [Source factories and run-make cases](../evidence-capped-pilots/README.md) and [distinct shipped-compiler baseline](https://github.com/astral-experiments/ohm/blob/e48abf3b09f415b296d0ee2e8ec81c0de7b50611/scripts/ruff-clap-config-help/evidence-release-24/README.md).

All six original histories observed four regenerated native library objects per role. The parent retained 232 of 236 library objects, and the candidate retained 237 of 241. The machine code behind the unaffected `CheckCommand` and `FormatCommand` derives stayed in their original physical files with the candidate. Newly emitted library object bytes fell from 2,288,712 to 1,113,336. Edited full CLI executables and every individual native library and binary object matched their own independently empty build. Each original and corrected CLI exercised the true help/configuration output. Both failed an invalid Rust edit with E0308 twice and repaired it. The independent clean control compares native bodies. Unrelated registry proc macros can produce different cold metadata in this checkout; per-state typed metadata is recorded separately.

Median cold OLD and empty NEW counts fell 0.009% each. The median OLD no-op fell 0.008% and the NEW no-op rose 0.002%. Every no-op had zero rustc and linker tasks. Allocated output on the edited state grew by 1,183,744 bytes at the median (1,146,880–1,191,936 bytes). The partition ledger also grows from 15,304 to 15,615 mono-item memberships, including duplicated inline copies. All compile and link work is included.

The separate [#26372 held-out edit](https://github.com/astral-sh/ruff/pull/26372) added a functioning `ruff format --extend-exclude` option. First builds took 5.02% fewer whole-command instructions and an independent forward repeat took 4.94% fewer. It had its own distinct initial/settled/clean native and diagnostic checks. The reverse metadata control is recorded in the [two-source pilot evidence](../evidence-capped-pilots/README.md).

Run `python3 -IB scripts/ruff-derived-impl-cgus/evidence-confirmed-28392/verify.py` from this checkout with `zstd` on PATH. It reopens all twelve original counters, their separately scoped kernel rustc invocations, fresh object membership, CLI verdicts and the 12 distinct edited native bodies kept in this small packet. The six original full archives also include the complete Ruff executable/control corpus and source-resolved ELF originals. Each machine’s immutable original artifact ID and SHA-256 is in its `N-binding.json`. [Six original hardware runs](https://github.com/astral-experiments/ohm/actions/runs/41741619584) and [independent complete native readback](https://github.com/astral-experiments/ohm/actions/runs/41745096907).

The [frozen hardware enrollment](https://github.com/astral-experiments/ohm/blob/d8596b7fafd31b4f959c7561a921d56705513956/.github/workflows/ci.yml) includes the exact ordinary command, two Rust source-bound SDK originals, native output and resource requirements. With these original source kits available, rerun the registered hardware workers with the following command.

```sh
gh-auto workflow run ci.yml -R astral-experiments/ohm \
  --ref charlie/qa-ruff-derived-impl-caps-20261103 \
  -f reviewed_head=d8596b7fafd31b4f959c7561a921d56705513956
```
