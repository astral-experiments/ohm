# Ruff #27470 and field visibility in check metadata

Both source compilers ran the same 12 rustcs on the real `Origin.path` edit. The whole `cargo check -p ty_server --lib` instruction difference changed sign between the two runner orders. We stopped at the registered two-host pilot. [Exact workload and decision rule](../matched-study.json) · [Completed run](https://github.com/astral-experiments/ohm/actions/runs/41570685416)

| Fresh host order | Parent instructions | Candidate instructions | Candidate change |
| --- | ---: | ---: | ---: |
| Parent, candidate | 39,904,110,081 | 39,975,741,340 | +0.180% |
| Candidate, parent | 39,986,481,228 | 39,957,585,155 | −0.072% |

The compiler change removed false dependencies on the contents of modules named by restricted field visibility. The edit changed a real field type and constructor. Across each host, the public fingerprints still changed for all 12 crates. In `ty_python_semantic`, 26,572 definition hashes changed on the parent and 23,958 on the candidate. The twelve edited rmetas grew from 28,381,112 to 28,381,775 bytes. Both cold instruction differences were below 0.006%, and all eight unchanged checks started zero compilers. [Source factory](https://github.com/astral-experiments/ohm/actions/runs/41568934075) · [Full integers and metadata](result.json)

The complete Cargo inventory contained 279 units. Each repair restored all 31 workspace metadata files to their edited bytes. Seven of the 31 matched an independently empty build byte for byte on each role and host. All successful ordinary checks emitted the same diagnostics. All four arms rejected the malformed producer with E0308. For privacy, we widened only `Origin.path` and compiled a field access in `ruff_db`. Narrowing just the producer caused the warm and empty checks to report the same E0616 at the untouched client. Widening the field again succeeded.

The first enrollment stopped before the privacy change because the historical snippet source contained two identically spelled field declarations. Its two unpaired historical observations are excluded from the table. The repaired enrollment selected the field by its containing struct and changes exactly line 526 of the original source. [First enrollment](https://github.com/astral-experiments/ohm/actions/runs/41569853037) · [Fixture](../visibility_probe.py)

The source pair used the same Cargo binary and LLVM and standard-library family. On the separately packaged `-23` release the same 12 rustcs ran, with 25.26 billion instructions overall and 14.49 billion in `ty_python_semantic`. [Signed release measurement](https://github.com/astral-experiments/ohm/blob/8095401c9f349463b1b6ab370bfc4fbc1a479672/scripts/ruff-linter-check-attribution/signed23-replay/README.md)

## Reopen the published measurements

From an Ohm packaging checkout, save the two original Actions archives and the previously published metadata decoder. The script verifies both archive SHA-256s, the decoder and table schema, the two independent boots, kernel-observed compiler arguments, matched whole-Cargo counters, field-access diagnostics and 48 old/edited metadata pair comparisons.

```sh
receipt_dir=$(mktemp -d)
decoder_dir="$receipt_dir/decoder"
mkdir -p "$decoder_dir"
gh_tool=/home/dev-user/.local/bin/gh-auto
"$gh_tool" api repos/astral-experiments/ohm/actions/artifacts/13200987895/zip > "$receipt_dir/41570685416-PC.zip"
"$gh_tool" api repos/astral-experiments/ohm/actions/artifacts/13201397849/zip > "$receipt_dir/41570685416-CP.zip"
decoder_commit=15e6fa8a50a723af261c7e1c0240b946882b0938
decoder_path=scripts/ruff-linter-check-attribution/ownership-replay
for file in rmeta.py compiler-schema.json; do
  "$gh_tool" api -H 'Accept: application/vnd.github.raw+json' \
    "repos/astral-experiments/ohm/contents/$decoder_path/$file?ref=$decoder_commit" > "$decoder_dir/$file"
done
study=scripts/ruff-linter-check-attribution/inline-visibility-result
python3 -IB "$study/reopen.py" "$receipt_dir" "$decoder_dir" > "$receipt_dir/reopened.json"
cmp "$study/result.json" "$receipt_dir/reopened.json"
```

The Actions archives have seven-day retention. Previously downloaded originals work with the same offline reader.
