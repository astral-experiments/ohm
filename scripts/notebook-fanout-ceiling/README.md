# Rust compiler samples on Ruff's notebook edit

This baseline run captures the compiler work and native outputs of `ty_python_semantic` and `ty_python_core`. It repeats the real signed-toolchain history that ruled out a 2× speedup from eight smaller compilers. The actual Linux perf, measured instructions, five regenerated native object files and the original producer library are part of the evidence. [Registered experiment](PLAN.md) · [Previous native object and sampling run](https://github.com/astral-experiments/ohm/actions/runs/41191199726)

Run from this reviewed packaging checkout under the configured OSS account.

```sh
qa_head=$(git rev-parse HEAD)
/home/dev-user/.local/bin/gh-auto workflow run ci.yml --repo astral-experiments/ohm \
  --ref charlie/qa-signed21-notebook-heavy-compiler-samples-v3-20261031 -f reviewed_head="$qa_head"
```

The independent reader takes the original Actions ZIP and its official SHA-256, run number and head, plus checkouts at the exact featureless and collector revisions in `sources.json`. It checks the Rust/Cargo SDK, real Cargo outputs and controls, recomputes the native ledgers and checks the available hardware samples. The baseline never assigns a speedup to a compiler change.

```sh
python3 -IB scripts/notebook-fanout-ceiling/reopen.py "$ZIP" \
  --feature "$FEATURE" --collector "$COLLECTOR" --zip-sha256 "$ZIP_SHA" --run "$RUN" --head "$QA_HEAD"
```
