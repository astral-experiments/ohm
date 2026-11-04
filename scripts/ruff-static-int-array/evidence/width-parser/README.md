# Parsing literal arrays in two Ruff dependency edits

Under the source-built C7 and C8 stage1 compilers, the full `unicode_width` rustc for Ruff #21231 used **1,008,866,002 → 905,853,130** Callgrind guest instructions (10.21% fewer). Its actual dependent, `ruff_formatter`, used 3,021,507,259 → 3,022,818,018 (0.043% more). On the separate #29261 RNG transition the actual `unicode_names2` compiler used 4,744,397,650 → 4,572,826,519 (3.62% fewer). These are single-process software counters. The whole ordinary Cargo hardware study has its own enrollment.

The compiler pair is #355 at `06fe634feaa39288210a6f17b8994346a5fae1c1` and its direct child `eda9434eda0b4f8519fc2257867ab7c7dd4b59fd`. The latter builds ordinary AST expressions from a complete positive schema over the existing token stream of a large literal array. It preserves the original token kinds, symbols, spans and punctuation. The bundled source diff includes the positive gate, fallback and native compiletest.

The fixed-HEAD #21231 history uses Ruff `b5305b5f328b03e3ba0ab1ba629dedb5c9f4415e` and only its historical Cargo.lock update from `64a255df497bede66fa4cdac80b9464d73a787ba`. Separate empty homes and actual compiler-specific products were used at identical visible paths. Unwrapped `cargo +ohm check -p ruff_formatter --lib --locked --offline` checked 42 units from empty, had two empty repeat rosters, compiled exactly `unicode_width` and `ruff_formatter` on the lock edit and zero on its repeat. The worker observed actual kernel rustc execs on that history, then reissued their original argv, cwd and environment in dependency order under Callgrind from each independent pre-edit state. Each profiled compiler produced exactly the same entire rmeta as the genuine edit. An earlier mixed sandbox/host instrumentation history compiled 40 units on the edit and was excluded. Its phase record and the earlier ptrace refusal are retained.

Separate untraced Cargo builds linked a real Ruff formatter reader. In each compiler, the complete edited, unchanged and independently empty executable was byte-identical. Of 1,112,064 scalars, 197 changed both width and actual Ruff group wrapping at the two enrolled line budgets. All 3,336,192 native output bytes agreed across compilers on each source. An independent build of both original registry revisions under `rustc --test` ran the normally cfg-disabled 20,034-row normalization table, with equal expanded source across compilers and full edited/empty native equality within each. Intentionally malformed first and last real rows still failed with identical diagnostics. The first-row full rustc was 946,753,902 → 943,606,568 instructions. The last-row rustc was 1,020,508,382 → 1,023,906,535. Repair and independent original produced equal executables in each role.

All 28 supplementary commands per compiler were reopened, including 17 exact real diagnostics (five inside disabled code), six AST/expanded/typed dumps and two executed clients. A real proc macro hashes the observed delimiter/spelling/spacing/spans and source text. The RNG history uses the original `523d83c941cb…→bfedc614b767…` edit. All 11 edited check units and zero repeat units were accounted for. The linked reader returned the same Unicode names/aliases across the edit, as required for a change to hash-table construction, and its full edited ELF equaled settled and independent empty in both roles. Both compilers' raw incremental `unicode_names2` build rlibs differed from independent empty on this RNG shape. Native bytes were checked within each compiler against its own clean output. Across the two separately source-built toolchains all eight recorded executable comparisons have different `.text` payloads. The section lists and complete file hashes are in `verified.json`, alongside the matching semantic and native-output checks.

## Independent replay

Run these commands from this directory, on a machine with Python 3 and zstd. The reader checks every one of 249 entries, including original complete ELF, rmeta, genuine per-process Callgrind summaries, runtime scalar bytes, parser diagnostics, native negative and repaired outputs, and the content-addressed projection of the selected kernel argv. The original C8 factory was [run 41861317302](https://github.com/astral-experiments/ohm/actions/runs/41861317302) at packaging `536b308a897a161771d3d9ce4f7de737a27dd81e`. The preceding C7 factory was [run 41753724558](https://github.com/astral-experiments/ohm/actions/runs/41753724558). The two original SDK and receipt object identities are in `decision.json`.

```sh
sha256sum --check SHA256SUMS
python3 -IB verify.py > /tmp/width-parser-verified.json
cmp /tmp/width-parser-verified.json verified.json
```

To repeat the supplementary source and diagnostic controls with the two independently installed source kits, copy `semantic.py` to a fresh empty directory. Each rustup home below must expose its actual source-bound compiler as toolchain `ohm`.

```sh
python3 -IB semantic.py c7 "$C7_RUSTUP_HOME"
python3 -IB semantic.py c8 "$C8_RUSTUP_HOME"
```
