# Large static integer arrays with release-optimized compilers

On Ruff’s Unicode generator update, bulk lowering saved **36.19% of the instructions in the affected check compiler** and **7.79% across the complete edited Cargo check**. During a build, it saved 32.65% in rustc and 7.59% across Cargo. Both compilers were built independently with Ohm’s Linux release recipe, including PGO, ThinLTO and BOLT. [Ruff edit](https://github.com/astral-sh/ruff/pull/29261) · [Six paired measurements](https://github.com/astral-experiments/ohm/actions/runs/41751693389)

| Edited command | Instruction count | Parent, billions | Change, billions | Median paired reduction | Paired range |
| --- | --- | ---: | ---: | ---: | ---: |
| `cargo +ohm check -p ruff_unicode_names2 --lib` | Affected rustc | 4.930 | 3.146 | 36.194% | 36.176%–36.755% |
| Same check | Entire command | 22.959 | 21.168 | 7.791% | 7.763%–8.017% |
| `cargo +ohm build -p ruff_unicode_names2 --lib` | Affected rustc | 5.488 | 3.696 | 32.652% | 32.575%–33.212% |
| Same build | Entire command | 23.464 | 21.684 | 7.586% | 7.531%–7.630% |

The two middle columns are separate medians. The reductions use the ratios within each pair. The six machines ran three trials in each order. All six improved the primary edited-check rustc measurement. The exact two-sided sign test gives p = 0.03125 and the minimum-to-maximum interval has 96.875% coverage for the median. All six machine identities differ from the earlier eight stage 1 measurements. [Stage 1 measurements](../README.md)

The complete cold check and build at the parent Ruff revision used 5.79% and 5.50% fewer instructions. The independently empty check and build at the edited revision used 7.39% and 7.19% fewer. On an unchanged call the paired medians moved by less than 0.01%. Each historical edit compiled 11 units, including the generator and its changed dependencies. The directly measured affected crate was `unicode_names2`. [Registration](registration.json)

We reopened both original SDK archives. They contain the signed `-24` Cargo and Wild, the expected rustc commit, and a compiler driver with a BOLT ELF note. Each compiler used its own PGO training for rustc, rustdoc, Clippy and rustfmt. Each worker checked those same physical compiler digests and ran the literal-array probe before measuring. [Parent build](https://github.com/astral-experiments/ohm/actions/runs/41737296261) · [Changed build](https://github.com/astral-experiments/ohm/actions/runs/41742694783) · [Compiler records](physical.json)

Across both compilers, the ordinary and separately observed edits, unchanged build, repaired build, and independently empty build produced byte-identical executables within each arm. The genuine edit changed the executable. The verifier runs all four distinct ELF programs against 153,626 Unicode names, 481 aliases and three negative cases, checks the original archive members, and reopens the two failed overflow attempts on each worker.

The 5,577,651-byte packet reconstructs all six original GitHub artifacts, totaling 130,745,575 bytes. From the packaging repository root, run this on x86-64 Linux.

```sh
python3 -IB scripts/ruff-static-array-cost/evidence/trained/verify.py --run-native
```

While the Actions artifacts are retained, add `--gh-auto /home/dev-user/.local/bin/gh-auto` to compare the six reconstructed ZIP digests against GitHub. To repeat the actual six measurements with the original trained compiler inputs, use the pinned workflow.

```sh
/home/dev-user/.local/bin/gh-auto workflow run ci.yml -R astral-experiments/ohm \
  --ref charlie/qa-rc24-trained-rand-20261104 \
  -f reviewed_head=71ee962005d6518812457ef1122712d7f93b196e
```
