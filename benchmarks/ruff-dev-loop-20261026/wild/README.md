# Ruff edit, build and test with Wild ThinLTO

Ohm 1.99.0-14 bundles the upstream Wild 0.11.0 executable for native Linux x86-64. We compared that executable with the same release built with cross-crate ThinLTO. The draft coordinator recipe uses the pristine upstream source and checks the digest of the resulting binary before packaging it.

| Ruff workspace command     | Whole-command instruction reduction | Wild instruction reduction |
| -------------------------- | ----------------------------------: | -------------------------: |
| `cargo +ohm build`         |              2.10% (2.08% to 2.12%) |                      3.42% |
| `cargo +ohm test --no-run` |              0.96% (0.84% to 1.07%) |                      3.45% |

Each command ran at the Ruff workspace root with a warm target directory. The build alternated the case of the first character in `"ruff failed"` in `crates/ruff/src/main.rs`. Only the `ruff` binary rebuilt among 501 Cargo unit records. The test build alternated the case of the first character in `"Unformatted code to be valid syntax"` in `crates/ruff_python_formatter/tests/fixtures.rs`. Only the `fixtures` integration test rebuilt among 619 unit records. The commands emitted six and 102 executables, respectively. We compared their SHA-256 digests with the native compiler and linker output for the same source bytes on every measured command. Tests did not execute.

We used 12 randomized blocks per command. Each block measured the released linker, the packaged ThinLTO linker and a ThinLTO linker with an additional debug-relocation fast path. We restored the opposite source bytes with the released linker before each observation. Each edit direction occurs in six blocks. Values are geometric means of within-block instruction ratios. Intervals use 40,000 block-bootstrap resamples stratified by edit direction. Two-sided randomization tests enumerate all 4,096 ways to exchange the two compared arms within blocks. The two package contrasts in each command used a family threshold of 0.05 across four planned comparisons.

Both ThinLTO comparisons have two-sided p = 0.000488 (build) and 0.000488 (test build).

The additional debug-relocation change changed full-command instructions by +0.20% for build and +0.10% for the test build compared with ThinLTO alone. The packaging draft selects pristine upstream code. [Individual process counts, order, source digests and output digests](shipping.csv)

## Measure the package

Use Python 3.11+, Valgrind Cachegrind, Clang and an installed x86-64 Linux Ohm 1.99.0-14 toolchain. Create a private rustup home and two disposable Ruff worktrees at `93526150df078af7dd8fc4226cdcc469539d2001`. A clean target and roughly 6 GiB for build or 18 GiB for test worked on this host. The source checkouts must remain at the same paths during a run. Set `EVIDENCE` to this directory and `COORDINATOR` to the coordinator checkout with the ThinLTO change.

```sh
export RUSTUP_HOME="$RUN/rustup"
rustup toolchain link ohm "$OHM_14"
export CARGO_BUILD_BUILD_DIR="$RUN/shared-build"
export CARGO_TARGET_DIR="$RUN/build-target"
cargo +ohm fetch --locked --manifest-path "$RUFF_BUILD/Cargo.toml"

SHIPPED="$(rustc +ohm --print sysroot)/lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
python3 "$COORDINATOR/scripts/prepare-wild.py" "$COORDINATOR/toolchains/1.99.0/15.json" \
  x86_64-unknown-linux-gnu "$RUN/thin"
python3 "$EVIDENCE/build-control.py" relocations "$COORDINATOR" "$RUN/relocations"

taskset -c "$CPUS" python3 "$EVIDENCE/measure.py" build "$RUFF_BUILD" "$RUN/count-build" \
  "shipped=$SHIPPED" "staged-thin=$RUN/thin/wild" "staged-combined=$RUN/relocations/wild"
CARGO_TARGET_DIR="$RUN/test-target" taskset -c "$CPUS" python3 "$EVIDENCE/measure.py" \
  test "$RUFF_TEST" "$RUN/count-test" \
  "shipped=$SHIPPED" "staged-thin=$RUN/thin/wild" "staged-combined=$RUN/relocations/wild"
python3 "$EVIDENCE/analyze.py" "$EVIDENCE/shipping.csv" shipped staged-thin
```

The runner records the randomized plan and digests before warmup. It copies each linker to a stable private path and holds the installed compiler fixed. Warmup and resets instrument Cargo while children execute natively. Cachegrind records user-space instructions from the final executable image after each exec. Every measured edit accounts for Cargo, rustc, the Clang driver and Wild. It requires exactly four complete `Ir` profiles and checks the full unit graph, dirty unit, executable contents and process exits. The explicit Clang driver and Wild's `--no-fork` keep exec and fork accounting unambiguous with Valgrind 3.22. Absolute counts vary with paths, cache state and host software. The comparison uses matched source bytes and the same worktree for every arm.

The devbox had an AMD EPYC Milan x86-64 CPU, Linux 6.8, Ubuntu 24.04 and Clang 18.1.3. The benchmark used CPUs 12–19, four Cargo jobs and the same trusted shared build directory. Cargo was `461a3d1007ecc997a6d86c7d75e8b518575c8d90` and rustc was `f1a7cf9d20b2cae39e991b178b56ba06b43dc8fa`. The source archive came from Wild `e856d81f6683cad80b9fe0ebf1a0c3c403c6fe11`.

| Wild arm                                               | Executable SHA-256                                                 |
| ------------------------------------------------------ | ------------------------------------------------------------------ |
| Released 0.11.0                                        | `0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5` |
| Pristine source, ThinLTO                               | `076b2067722a82b6445183fcabc26a17819537e1656067ec85947b5800ba2a23` |
| ThinLTO plus experimental debug relocations            | `06656bf54bbfad2ae2b669eceb79740c1456a8421dd160ae4aaeabc614d176ba` |
| Pristine source, upstream profile, same pinned builder | `1079dffdaee2bc9f81a8aebd800339fdbc3922c08c31cb319c7cc70cec2bb76b` |

## Independent comparisons

An earlier experiment built each Wild arm with Ohm 1.99.0-6 from the same upstream Git archive and ran Ruff with release-14 Cargo and rustc. Against the same-compiler unmodified linker, ThinLTO reduced whole-command guest instructions by 1.925% for `build -p ruff --bin ruff` and 0.671% for `test -p ruff_python_formatter --test fixtures --no-run`. The debug-relocation fast path alone reduced these counts by 1.307% and 0.408%. All four contrasts favored their candidate in 12 of 12 randomized pairs. One CLI attempted measurement after a change to the compiler inode timestamps. It triggered dependency rebuilds and was discarded. The CLI run restored warm artifacts before restarting that block. The first and second six blocks use independently verified native output digests. The main package comparison used fresh worktrees and targets after this event. [Targeted counts and digests](screened.csv)

The earlier package-targeted native timings included 36 randomized ABBA or BAAB blocks per command. The 95% intervals for elapsed-time reduction included zero for both the CLI build (−5.37% to +0.40%) and formatter test build (−1.27% to +2.18%). The package results above report instructions. [Native timings in nanoseconds](native-wall.csv)

Changing only the Cargo profile in the pinned Rust 1.99.1 builder cut Wild's own instructions by 3.57% on a saved Ruff CLI link and 3.18% on a saved Ruff test link. Each of eight pairs per link matched the complete executable from the native Rust build. The control builder can recreate this upstream-profile executable with the `upstream-profile` argument. [Link-only counts and executable digests](link-only.csv) · [Capture and comparison tools](https://github.com/astral-sh/ohm-wild/tree/c7531239c33df0dab09e4c6357013f10e5857da8/benchmarks/ruff-dev-loop-20261026/debug-relocations)

Two clean container builds from the release recipe with four and eight Cargo jobs reproduced the same ThinLTO executable. The [packaging change](https://github.com/astral-sh/ohm/commit/b9a97e7d59169bc6596a8ba653557827c836a921) pins the upstream source archive, amd64 Rust image and final binary digest. The upstream package uses 10,319,072 bytes and the ThinLTO executable uses 10,554,960 bytes. Both require at most GLIBC_2.34.
