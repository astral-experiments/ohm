# Ruff package test builds after the renderer edit

Letting Cargo replay code generation for the twelve binary examples reduced the first unchanged package test build from 2.558 to 2.096 billion retired user instructions. All six independently registered Linux workers improved. Each worker contributed two matched pairs in reversed order. The parent compiled all twelve examples again. The candidate reused their code generation and still invoked Wild for every example. [Original hardware run](https://github.com/astral-experiments/ohm/actions/runs/41413027168) · [Raw counts, digests, and storage](test-build-result.json)

The command was `cargo +ohm test -p ruff_annotate_snippets --no-run --locked --offline -j4 --message-format=json`. The changed source was Ruff’s two-file renderer edit. The intervals below use the six boot-level log ratios and all 46,656 paired-bootstrap resamples. The p-values use all 64 paired sign assignments. Positive reductions mean fewer retired user instructions. [Frozen measurement plan](TEST-CONFIRMATION.md) · [Matched Cargo binaries](original-factory.json)

| Cargo phase | Instruction reduction | 95% paired interval | Two-sided p |
| --- | ---: | ---: | ---: |
| First unchanged, primary | 18.1038% | 18.0790% to 18.1283% | 0.03125 |
| Settled unchanged | 18.4903% | 18.4559% to 18.5242% | 0.03125 |
| Real edit plus first unchanged | 3.4276% | 3.3802% to 3.4862% | 0.03125 |
| Real edit | −0.0681% | −0.1304% to 0.0079% | 0.15625 |
| Cold | −0.0063% | −0.0139% to 0.0022% | 0.21875 |

The warm target and build directories contained 1,073 files at baseline and 1,217 with the candidate. The median allocated footprint grew from 161,153,024 to 163,526,656 bytes, an additional 2.26 MiB. Hard links were counted once and the raw ledger separates saved links, manifests, and object files.

All 17 examples and test executables matched complete signed files enrolled independently for OLD and NEW before these measurements. Each worker checked both arms immediately after applying the edit, before an unchanged command could repair a stale output. It also checked the independent empty NEW build. All twelve examples had identical complete files and observable output under both Cargo binaries. Across the six workers the receiver rechecked 54 complete runs of the package’s 241 integration cases, including the renderer regression’s expected OLD panic and its NEW output. A separate physical control verified changed native constructors, the higher-priority native library, a malformed native library, Rust E0308, and repair. [Signed reference and source-specific verdicts](https://github.com/astral-experiments/ohm/actions/runs/41412344287) · [Native and Rust error gate](https://github.com/astral-experiments/ohm/actions/runs/41407253489)

The first six test-build workers failed their original raw equality check, including on baseline Cargo. Their counts are excluded. Replaying the signed Wild command with frozen original inputs demonstrated how grouping changes the ELF read-only data section's entry size, which also changes the GNU build ID. The new registration allowed only preregistered complete files for each source state. Every other byte identity would fail. [Rejected original measurements](https://github.com/astral-experiments/ohm/actions/runs/41407781135) · [Frozen signed Wild control](https://github.com/astral-experiments/ohm/actions/runs/41410572959)

## Reopen the original measurements

In an authenticated checkout of the Ohm packaging repository, download the six original action archives, verify their GitHub SHA-256 digests, and run the reader from the measured revision. The reader checks native process traces, complete signed output identities, raw test verdicts, raw hardware counters, and the independent boots before calculating the paired intervals.

```sh
set -eu
run_dir=$(mktemp -d)
api=repos/astral-experiments/ohm/actions
gh-auto api "$api/runs/41413027168/artifacts" \
  --jq '.artifacts[] | [.name, (.id | tostring), .digest] | @tsv' > "$run_dir/artifacts.tsv"
while IFS="$(printf '\t')" read -r name id digest; do
  gh-auto api --allow-escape-sequences "$api/artifacts/$id/zip" > "$run_dir/$name.zip"
  printf '%s  %s\n' "${digest#sha256:}" "$run_dir/$name.zip" | sha256sum --check --status
done < "$run_dir/artifacts.tsv"
git show 612ed6519a7b69b5b583ea9cf7c4d98a110010ea:scripts/ruff-example-replay/reopen.py > "$run_dir/reopen.py"
python3 -IB "$run_dir/reopen.py" confirm-tests "$run_dir"/ruff-example-replay-confirm-tests-*.zip
```
