# Rust #276 and developer-mode Ruff AST test builds on Apple silicon

Rust #276 skipped one `zmij` compilation, but none of the four measured endpoints reached the predeclared 2× threshold in both orders. The combined edit and first unchanged command improved from 2.516 s to 2.409 s with the parent first and from 2.530 s to 2.318 s with the candidate first. The screen stopped with zero held-out pairs. The two observed ratios per endpoint do not establish an interval or an instruction result. [Frozen test-only protocol](https://github.com/astral-experiments/ohm/blob/80a6e1bca9f57532884126a90a942269ef9bb530/scripts/ohm-apple-zmij/ast293-real-test-plan.md) · [Native run](https://github.com/astral-experiments/ohm/actions/runs/41085814126)

Each pair below reports parent and candidate wall times in seconds. Each role and endpoint started in its own empty target and shared build directories. The combined endpoint ran two consecutive Cargo commands under one uninterrupted clock. Tests and native-output verification ran after each measured endpoint.

| Measured `cargo test --lib --no-run -p ruff_python_ast` endpoint | Parent first (P, C) | P/C | Candidate first (P, C) | P/C |
|---|---:|---:|---:|---:|
| Edit + first unchanged | 2.516221, 2.409467 | 1.044× | 2.530468, 2.317707 | 1.092× |
| Edit | 1.786629, 1.623625 | 1.100× | 1.780611, 1.650666 | 1.079× |
| First unchanged | 0.743738, 0.648482 | 1.147× | 0.777352, 0.699190 | 1.112× |
| Second unchanged | 0.779205, 0.656437 | 1.187× | 0.744530, 0.710510 | 1.048× |

The parent was Rust #275 `2035696c5316079f5b2e4373aee834839aac97e9`, and the candidate was #276 `444c0273a2e2bc0b161e988d43c882349bc2d7a6`. Both used the same native Cargo #293 `735e1528ed741015c57676dccf05dbdc0ff7bed1`, `--locked --offline -j4` and the positive developer-environment allowlist. Actual local rustc invocations contained `-Cincremental`. The source transition `b5dba861cc38e3f7fb4524c9ceba3e01a474ea13` to `7b13f01ba1569887a25670820764b24c206da8e5` added `nodes::tests::f_string_parts`. Both old and new builds executed their full expected inventories of 53 and 54 tests, respectively. [Ruff edit](https://github.com/astral-sh/ruff/commit/7b13f01ba1569887a25670820764b24c206da8e5)

The separate structural visits reproduced the same counts in both orders. Each cold build used 36 full compilers, zero link-only compilers and nine Xcode links. The edit and repair used two full compilers on the parent and one on the candidate, with one real Xcode link each. Both unchanged parent builds ran one full `zmij` and one link-only `ruff_python_ast`. The candidate ran just that link-only compiler. Neither arm invoked Xcode ld on these repeats. Both rejected invalid source with E0425. The 392 native provider commands passed the registered checks. All 20 physical links, eight same-installation executable reuses, 16 independent timed endpoint products, and the available 53/54-test clean outputs passed signed-program, Rust object and behavioral checks. The old library result remains separate. [Earlier developer-mode library and test study](../native-apple-276-developer-293-v2/README.md)

## Reopen

From this directory, run `sha256sum -c SHA256SUMS` and `python3 -IB verify.py` with Python 3.11+ and zstd available. The verifier uses the explicitly versioned [signed-program reader](../native-apple-276-developer-293-v2/readback/) in this evidence tree. It reopens both typed Cargo streams for each combined endpoint, checks every native test executable and its codegen inputs, replays the complete test verdicts, and prints the exact paired nanoseconds. The separately retained 1,943,548-byte packet contains 1,007 selected original members mapped to decoded SHA-256 values. The original 55,408,649-byte Actions ZIP SHA-256 is `50303b31f31c79af497c2451c6bf943db0ac4cec95ed910a842ade12e5a0bd59`. [Original artifact](https://github.com/astral-experiments/ohm/actions/runs/41085814126/artifacts/12993185613)
