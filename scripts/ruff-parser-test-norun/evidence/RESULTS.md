# Full Ruff parser test-build instructions

The whole `cargo +ohm test -p ruff_python_parser --lib --no-run --locked --offline --message-format=json` command used **5.555% fewer retired user instructions** at the paired median after the real Ruff #29261 edit. The command used two Cargo build jobs. The source-built stage1 parent is `f5a51d8cc3e76236c2d0f17d495d59ebb03306e4` and the candidate is `6c2874a0b6a0bf3570f8959733b6f87907e5cce6`. Both use Cargo `abc70d60`, the same stock Wild, the same dev profile and the same 502 registered archives. [Historical Ruff edit](https://github.com/astral-sh/ruff/pull/29261) · [Compiler change](https://github.com/astral-experiments/ohm-rust/pull/353)

Across the six independent confirmation boots, the parent and candidate medians were 65.687B and 62.034B instructions. The six paired savings ranged from 5.532% to 5.589%. The paired minimum-to-maximum interval has 96.875% distribution-free coverage under independent continuous observations. All six improved. The two-sided exact paired sign p-value is 0.03125. [Confirmation run](https://github.com/astral-experiments/ohm/actions/runs/41751977762)

| Block | Order | Parent instructions | Candidate instructions | Saving |
|---|---|---:|---:|---:|
| B1 | CP | 65,691,786,404 | 62,030,930,813 | 5.573% |
| B2 | PC | 65,694,767,267 | 62,047,444,342 | 5.552% |
| B3 | PC | 65,676,733,521 | 62,043,249,217 | 5.532% |
| B4 | CP | 65,674,099,932 | 62,033,292,402 | 5.544% |
| B5 | CP | 65,687,233,615 | 62,016,198,220 | 5.589% |
| B6 | PC | 65,685,915,388 | 62,035,435,602 | 5.557% |

| Whole command | Median parent instructions | Median candidate instructions | Median paired saving |
|---|---:|---:|---:|
| Cold OLD | 566,692,910,897.5 | 562,935,467,333 | +0.665% |
| Edited NEW | 65,686,574,501.5 | 62,034,364,002 | +5.555% |
| Settled NEW | 255,505,587 | 255,452,906 | +0.013% |
| Independently empty NEW | 553,504,231,344 | 549,734,612,282 | +0.683% |

In a separate kernel-traced replay of the same edit, each role ran 12 physical crate compilers and two stock Wild processes. The following medians are per-compiler lifetime observations. The primary whole command used an untraced inherited counter.

| Observed compiler | Parent instructions | Candidate instructions |
|---|---:|---:|
| `unicode_names2` | 10,103,097,878.5 | 6,449,188,487 |
| `ruff_python_parser` | 33,816,502,390 | 33,823,072,765 |

The separate two-boot screen saved 5.560% and 5.624%. It admitted the six confirmations and contributes zero observations to their estimate. [Pilot](https://github.com/astral-experiments/ohm/actions/runs/41750317176)

## Native and error checks

Each role reported 148 cold OLD products, 12 of 145 products dirty on the genuine edit, zero on the settled visit, and 145 of 145 freshly built in an independent NEW. Both invalid checks rejected the overflowing `256` with the exact half-open byte range `23875..23878` in the Unicode source. After repair, the entire parser executable matched that role’s edited, settled, separately traced and independently empty output. Every successful visit listed exactly 246 tests and passed the real `lexer::tests::lex_fstring_missing_brace` outside the measured command. The offline reader reran each distinct ELF.

- P OLD `0f1a069acb3c81abe7b030187ed3117a8fc8a56a8c6e6fd64c605d6525adc3b6`.
- P NEW `b3da9f865ed22b46565ef447d2fcd8c6ba4df4cfcf91fca5b3e4ead0c09f6123`.
- C OLD `e47d5a9c5d882157db521e8aae4ba853de8db3e260a4b50bda133e6596f6e102`.
- C NEW `120cbc5eed05e4ea10e7081e340c102c3af58f3fd89c9ad4c535cc066ff262d1`.

The two compilers produce different full test binaries, including differences in loaded code and data. The archive retains all four complete binaries. Their parser compiler invocations used the same literal `-C metadata=b15ebff3cb7e2335` and `-C extra-filename=-32d57a91066dd3f5`. The strict equality comparison uses the independent cold output of the same source-built compiler. [Section digests](cross-role-sections.json)

## Reproduce the original counts

The shared payloads and per-boot records reconstruct all eight original CI ZIPs byte for byte. Each ZIP is checked against its original GitHub artifact size and SHA-256. An independent reader then checks the literal Cargo commands, unmultiplexed hardware events, both ordered SDKs, full generated files, raw errors and complete executable bytes. The standalone review needs x86-64 Linux, Python 3.11 or later and zstd. The packet stores identical compressed native entries once. Rebuilding the original ZIP verifies every header and counter record as well as the native payload.

```sh
qa=scripts/ruff-parser-test-norun
out=$(mktemp -d)
python3 -IB "$qa/originals.py" restore "$qa/evidence/originals" pilot "$out/pilot"
python3 -IB "$qa/review.py" pilot "$out/pilot" bb6dc52abeecc53c667a1f473981c9d9abab80d8 41750317176 "$out/pilot/verified.json"
python3 -IB "$qa/originals.py" restore "$qa/evidence/originals" confirmation "$out/confirmation"
python3 -IB "$qa/review.py" confirmation "$out/confirmation" 5380de2b4712546142ce8a10356d02c0c00103fd 41751977762 "$out/confirmation/verified.json"
```

To inspect the exact edited candidate executable from block B1, extract its content-addressed member from the reconstructed ZIP.

```sh
digest=120cbc5eed05e4ea10e7081e340c102c3af58f3fd89c9ad4c535cc066ff262d1
unzip -p "$out/confirmation/13286988881.zip" "native/$digest.zst" | zstd -dc > "$out/candidate-parser"
printf '%s  %s\n' "$digest" "$out/candidate-parser" | sha256sum -c -
chmod u+x "$out/candidate-parser"
"$out/candidate-parser" --exact lexer::tests::lex_fstring_missing_brace
```

The registration fixes the whole-command threshold, both native verdicts, the cold and settled control, and the independent role order. The separately measured owner counts attribute work within the edit. [Original registration and reader](https://github.com/astral-experiments/ohm/tree/bb6dc52abeecc53c667a1f473981c9d9abab80d8/scripts/ruff-parser-test-norun)
