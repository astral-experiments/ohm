# Ruff response-file edit with the objc2 frame marker

On Apple Silicon, twelve pairs of warm CI builds measured the change from rustc 82911b51 to 7924254a using the same Cargo 735e1528 from Ohm Cargo #293. Ruff #28877 changes how ty interprets literal paths starting with `@`. Every old CLI accepted the inputs and every edited CLI emitted both expected diagnostics. The command was `cargo +ohm build -p ty --bin ty --locked --offline -j4 --message-format=json`. Cargo inherited `CI=true`, which disables rustc incremental compilation. [Historical Ruff edit](https://github.com/astral-sh/ruff/pull/28877), [experiment design and source](https://github.com/astral-experiments/ohm/tree/3bdeb29d225ac56793e22c7be9b1ac3c83bec4af/scripts/ohm-apple-zmij), [run](https://github.com/astral-experiments/ohm/actions/runs/41072664769).

| Whole Cargo command | Parent median | Candidate median | Paired median | 96.14% paired interval |
| --- | ---: | ---: | ---: | ---: |
| Real edit | 1.980 s | 1.597 s | 1.240× | 1.231–1.244× |
| First unchanged build | 0.747 s | 0.349 s | 2.150× | 2.126–2.196× |
| Second unchanged build | 0.743 s | 0.347 s | 2.147× | 2.129–2.165× |
| Edit plus first unchanged build, sum of the two measured commands | 2.726 s | 1.946 s | 1.399× | 1.393–1.413× |

The first unchanged build was the registered primary endpoint. All twelve pairs exceeded 2×, with an exact one-sided balanced randomization p-value of 1/924. The two earlier mirrored pilots were separate. Each held-out pair used fresh target and build directories. Both roles actually linked the edited CLI and both ran Apple's linker on each unchanged build. The candidate removed the full `objc2` compile, leaving one link-only `ty` compiler and one native link. Cold and edited commands yielded 353 and 354 typed Cargo units. The measured and traced freshness sets agreed in every installation.

All 96 returned programs in the confirmation sequence matched their own compiler's corresponding empty build byte for byte and produced the correct output and exit. An invalid edit failed and the repaired CLI matched clean. Across 392 separate provider builds, Cargo #293 followed closed-over and higher-priority native inputs, reported missing and malformed inputs, and repaired identically to empty builds. The defaults-off controls expose twelve stale outcomes. Median hardlink-deduplicated allocated space across target and build directories was 1,478.14 MiB on the parent and 1,477.85 MiB on the candidate. The hardware instruction counter could not establish descendant coverage, so the table uses wall time.

The same compiler patch is unsafe with signed -20 Cargo at 2d44bd4a. Across 196 warm-versus-empty comparisons, ten candidate default-mode builds returned the previous executable after an undeclared native input changed. Higher-priority archives and in-place overwrites returned the prior value. Removing or corrupting the archive could report success. The changed inputs appeared both directly and through a dependency. In all ten cases the warm build ran zero native links and the empty reference ran one. Both compilers passed the declared-input and genuine Rust-edit cases. The parent passed every defaults-on case. A release using this compiler optimization needs a compatibility fallback for older Cargo versions. [Signed Cargo run](https://github.com/astral-experiments/ohm/actions/runs/41085838553), [observed verdicts](signed-cargo.json).

To reopen the 12 pairs from the original archive while GitHub retains it, run these commands from a checkout of this evidence branch.

```sh
gh-auto api repos/astral-experiments/ohm/actions/artifacts/12991680853/zip > /tmp/objc2-warm-ci.zip
python3 scripts/ohm-apple-zmij/evidence/objc2-warm-ci/verify.py /tmp/objc2-warm-ci.zip
```

To rerun the study on fresh Apple hardware, verify the workflow ref before dispatch.

```sh
test "$(gh-auto api repos/astral-experiments/ohm/git/ref/heads/charlie/qa-apple-objc2-ty-cli-clock --jq .object.sha)" = 3bdeb29d225ac56793e22c7be9b1ac3c83bec4af
gh-auto workflow run ci.yml -R astral-experiments/ohm --ref charlie/qa-apple-objc2-ty-cli-clock
```
