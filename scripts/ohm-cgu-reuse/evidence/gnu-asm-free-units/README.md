# Incremental LLVM reuse on a Ruff build

Changing Ruff’s Python version defaults from 3.14 to 3.15 regenerated 95 LLVM units for `ruff_python_ast`. On the next unchanged build, the compiler generated all 95 again. One unit included assembly. With the patch, the edit generated two units and the repeat generated one. Every other reused object came from rustc’s existing incremental session. [Ruff edit](https://github.com/astral-sh/ruff/commit/ef23c9c39eb3029bab0139c3ea7ae6d95c4131e0)

Each arm ran an ordinary `cargo +ohm build -p ruff_python_ast --target aarch64-unknown-linux-gnu --locked --offline -j4` on an x86-64 Linux host. Cargo and Wild were the physical binaries from Ohm 1.99.0-20. Both compiler SDKs were built from source with identical host and target libraries. Only the rustc driver differed. In both arms the measured command contained Cargo and three full rustc invocations, for `ruff_python_ast`, `compact_str` and `zmij`. Four original Callgrind profiles account for each command after rustup dispatched Cargo. The benchmark interface also requested Cargo's JSON output in both arms. [Registered protocol](../../counter-plan.md) · [Source and binary identities](source-equivalence.json)

| Build | Parent instructions | Patched instructions | Paired median speedup in instructions | 96.1% interval |
| --- | ---: | ---: | ---: | ---: |
| Real edit | 41.23 billion | 15.15 billion | 2.721× | 2.721–2.722× |
| First unchanged build | 38.77 billion | 12.37 billion | 3.133× | 3.133–3.135× |
| Sum of edit and repeat | 79.99 billion | 27.52 billion | 2.907× | 2.906–2.907× |

Twelve independent paired workers used the preassigned six parent-first and six child-first orders. The two primary endpoints each gave a one-sided probability of 1/924 against the sharp 2× null across all balanced assignments. The table reports userspace guest instructions. Median allocated storage for the private target and build directories was 158,363,648 bytes before and 156,362,752 bytes after. [Per-process counts and hosted decision](counts) · [Original run](https://github.com/astral-experiments/ohm/actions/runs/41088653170)

The old and new returned libraries contained all 95 native objects. The independently linked executable returned the expected version values before and after the edit, including on the first repeat and repair. The invalid Rust edit produced E0425. On the native assembly fixture, modifying bytes while preserving the file’s size and timestamp changed the returned program. Removing the input failed, and repairing it matched an empty build. Separate fixtures changed a PGO profile and the CPU used for native tuning. The compiler kept full regeneration in both settings. [Native and object results](final-guarded-cgu-independent-native-readback.json) · [External-input controls](profile-and-host-guards.json)

This comparison uses the Cargo shipped in -20 and the built-in GNU target. A separate GNU proposal recognizes specific AArch64 register assembly and uses a version-aware Cargo reader. Its results on the same Ruff edit overlap these results. The ratios cannot be multiplied. The current release candidate also contains an unrelated change to derive expansion that was outside this matched compiler comparison.

From the repository root, recompute all registered statistics using Python 3.11 or later.

~~~sh
python3 -IB scripts/ohm-cgu-reuse/evidence/gnu-asm-free-units/verify.py
~~~

While the original Actions artifacts are retained, a Linux machine can reopen the full Callgrind profiles, process traces, native objects and reader programs from the original 12 workers. The reader selects `gh-auto` when installed, otherwise `gh`. Start with a new output directory.

~~~sh
python3 -IB scripts/ohm-cgu-reuse/evidence/gnu-asm-free-units/collect_final_counter.py "$(mktemp -d)"
~~~

To build both compilers again and rerun the native controls, two pilot pairs and twelve confirmation pairs, dispatch the source rebuild. It uses the public Rust source, the pinned Ruff edit, the signed -20 tools and the compiler artifacts produced by that same run. The replay branch omits only the two jobs that reproduce defects in superseded prototypes.

~~~sh
gh-auto workflow run ci.yml --repo astral-experiments/ohm --ref charlie/proof-gnu-asm-free-codegen-units-20261030
~~~

## Independent source rebuild

A second run built both compiler drivers from source again and reproduced their byte identities. Its twelve new paired workers measured an instruction-count speedup of 2.721× for the real edit (96.1% interval 2.7208–2.7218×) and 3.134× for the first repeat (3.1338–3.1344×). Both one-sided probabilities against a 2× improvement were 1/924. The edit and repeat together had an instruction-count speedup of 2.907×. Median allocated storage was 158,363,648 bytes before and 156,364,800 bytes after. Each result uses this second run alone. The verifier above recomputes both cohorts separately. [Second run](https://github.com/astral-experiments/ohm/actions/runs/41102102686) · [Reopened per-process counts](source-rerun-41102102686/counts) · [Rebuilt SDK inventories](source-rerun-41102102686/final-source-built-sdk-manifests.json)

To reopen this run's original Callgrind profiles while the Actions artifacts are retained, use a fresh directory.

~~~sh
python3 -IB scripts/ohm-cgu-reuse/evidence/gnu-asm-free-units/collect_final_counter.py --run 41102102686 "$(mktemp -d)"
~~~
