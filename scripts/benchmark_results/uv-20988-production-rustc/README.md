# Production rustc instructions after uv #20988

This trial isolates two actual rustc processes during an ordinary workspace-root `cargo check --locked --offline -j8` after the landed uv workspace-glob edit. Both compilers use Ohm −22 sources with #318, the PGO/BOLT production recipe and the same signed −22 Cargo. The treatment adds #296 and #306. [uv edit](https://github.com/astral-sh/uv/pull/20988) · [Build qualification](https://github.com/astral-experiments/ohm/actions/runs/41374825846) · [Preregistered protocol](https://github.com/astral-experiments/ohm/blob/13294dce75bfc4959f4d1636730fa7a27082deb1/scripts/uv-20988-ctfe-hw/thread-protocol.json)

| rustc library | Corrected stock | With #296 + #306 | Median fewer instructions | Pairs above 20% | Simultaneous lower ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| `uv-lib` | 22.073B | 13.387B | **39.35%** | 8/8 | 1.648736× |
| `uv_resolver-lib` | 10.392B | 3.855B | **62.91%** | 8/8 | 2.695682× |

Each compiler had eight independently rebuilt pre-edit states on one calibrated Linux x86-64 host. The two groups of four pairs alternated compiler order. Each measured process matched an earlier off-clock kernel observation by executable inode, exact Cargo arguments, library kind and features. The resolver had `clap` and `schemars` enabled. A Linux hardware event counted retired userspace instructions for the selected process and its threads from its successful exec stop. On-host calibration checked serial work, three-thread work, exclusion of work in a forked child and rejection of a second exec.

The arm columns show their own medians. The paired percentage comes from the eight control-to-treatment ratios. The preregistered test required all eight ratios and both hold and order medians above 1.25×. Its one-sided matched sign test uses Bonferroni correction for both endpoints. The minimum of each eight-ratio series gives simultaneous lower bounds with at least 99.21875% coverage under independent matched signs. The separate twelve-pair study measured the ordinary wall time and the entire Cargo process tree. [Whole-command measurements](https://github.com/astral-experiments/ohm/tree/45b3dbb974f1c9fbce601daeb9296d6f85119e20/scripts/benchmark_results/uv-20988-production-root)

Run the verifier here with Python 3.11 or later. It reads the raw hardware ABI records, resolves the measured PIDs against the original kernel events and exact enrolled arguments, checks the on-host calibration and source/SDK/cold-build receipts, and recomputes both ratios and their statistics.

```sh
python3 -I verify.py
```

The compact archive includes 214 exact original members. To check them byte-for-byte, download the original Actions ZIP (406,775,499 bytes, SHA-256 `ed8aa6376104fcc84a9fe5566b4488f1e48cbdfea834376518d28795685abdcc`) and pass its path. The full artifact also includes the raw Cargo streams and serialized metadata used by the complete auditor. [Original upload](https://github.com/astral-experiments/ohm/actions/runs/41385306015/artifacts/13115768079) · [Full auditor](https://github.com/astral-experiments/ohm/blob/13294dce75bfc4959f4d1636730fa7a27082deb1/scripts/uv-20988-ctfe-hw/audit.py)

```sh
python3 -I verify.py --original /path/to/original.zip
```

A fresh physical rerun needs the pinned producer artifacts and a calibrated host. The workflow reapplies uv `b60da7ad468d5bb8a6b3dee7d7e54a47981f23c7` → `1979349b68dbaa936b98c0f409c1df0598fa72f1` at the same path for each visit and qualifies independently cold builds and two behavior fixtures. The two measurements represent the combined trait-lookup patches on this edit. [Measurement workflow](https://github.com/astral-experiments/ohm/blob/13294dce75bfc4959f4d1636730fa7a27082deb1/.github/workflows/ci.yml)
