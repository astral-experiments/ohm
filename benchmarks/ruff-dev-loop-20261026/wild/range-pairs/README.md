# Paired DWARF relocations on two historical Ruff edits

The full workspace `cargo +ohm build` workload applies and reverses the eight-file formatter change for nested quotes in format specifications. It rebuilds 19 Cargo units, starts 19 compilers and links eight times. Cargo reports six executable targets. The full workspace `cargo +ohm test --no-run` workload applies and reverses the two-file change that sorts formatter diagnostics. It rebuilds one integration-test target and links once. Cargo reports 102 executable targets. Every build uses Ruff `93526150df078af7dd8fc4226cdcc469539d2001`. [Formatter edit](https://github.com/astral-sh/ruff/commit/b3fb43af25f3d07758f953ce20ec900fc8812da2), [test edit](https://github.com/astral-sh/ruff/commit/2fb7c8ddd806aec98f8bba8f4c78d4a7c22f9d56)

The linker has three arms. `control` is the ThinLTO upstream Wild build proposed for Ohm. `middle` also contains the existing changes that resolve individual x86-64 debug relocations. `candidate` adds paired range and location endpoints to `middle`. All three use the same upstream Wild 0.11.0, the same pinned Rust builder image, the same PGO Cargo binary and the published Ohm 1.99.0-14 compiler. [ThinLTO packaging](https://github.com/astral-sh/ohm/pull/185), [individual relocation changes](https://github.com/astral-sh/ohm-wild/pull/42)

| Arm | Linker SHA-256 |
| --- | --- |
| `control` | `076b2067722a82b6445183fcabc26a17819537e1656067ec85947b5800ba2a23` |
| `middle` | `bb681a7ee1a50349d97ebbd7ac315c94dac7fcff8db3ff2e0fa93c2261fab7de` |
| `candidate` | `97cd2b7445d07159a210194340a0f8bdbfc08344fa4ea3afbd547f3309cd0cb4` |

The locked schedules use 12 blocks for each command. Each direction of the complete historical patch appears six times. The three arms run once per block, and the six possible orders appear twice each. Each scored command starts after Cargo has produced the opposite fixture state. The comparison checks the dirty units, the entire Cargo graph and the raw ELF bytes of every executable against a native build in the same context. Independent native traces establish the complete roster of successful application execs, including concurrent execs split by `strace`.

Cargo runs under DynamoRIO with child tracing disabled. Cachegrind records every rustc process and its Clang and Wild descendants using separate PID output files. The collectors have different instruction-count conventions, so the per-process data keeps both counts identifiable. The bootstrap rustup program, the shell that forwards to Clang, and the profilers are outside the application counts. `ir-0` is the primary instruction cohort. The test build also repeats that measurement using the independently frozen second schedule. Both use the same verified native product and process gates. [Counter source and calibration](../integrated.md)

## Reproduce

Use separate clean Ruff checkouts for the two commands. Install Cachegrind, Clang, `strace`, rustup and the released x86-64 Linux Ohm toolchain. Supply a pre-fetched Cargo registry for Ruff's locked dependencies. Reserve enough private disk for the full target and shared build directories plus 24 GiB of free space. The recorded CPU sets were 4–7 for the build and 12–15 for the test build on an AMD EPYC Milan host. The runner accepts any fixed set of four CPUs.

Build `control` using the coordinator checkout at `b9a97e7d59169bc6596a8ba653557827c836a921` with `scripts/prepare-wild.py`. Use `build-middle.py` with the coordinator packaging checkout for the control containing Wild #42. Run the same `scripts/prepare-wild.py` from that packaging checkout for the candidate. `setup.py` verifies all three executable hashes. Two clean coordinator recipe runs reproduced the measured candidate and both licenses. [Package and source digests](packaging.json) Use the PGO Cargo control built from `461a3d1007ecc997a6d86c7d75e8b518575c8d90`, the DynamoRIO 11.91.20741 runtime, and the client built from the adjacent `counter/` directory. [Cargo build recipe](https://github.com/astral-sh/ohm-cargo/tree/a9f8eccf2cc63a7f648ea262a66a8a8ed4a737ad/benchmarks/ruff-dev-loop-20261026/cargo-stack), [DynamoRIO client](../counter)

```sh
python3 setup.py build "$study" --ruff "$ruff" --toolchain "$release14" \
  --cargo "$pgo_cargo" --cargo-home "$registry" \
  --drrun "$drrun" --pidcounter "$pidcounter" \
  --control "$thin" --middle "$individual" --candidate "$paired"
for action in native count-audit measure; do
  taskset -c 4-7 python3 measure.py build "$action" --state "$study" \
    --fixture formatter-holdout --control "$thin" --middle "$individual" --candidate "$paired"
done
python3 export.py build "$study/results" "$raw"
python3 analyze.py "$raw/build.csv"
```

Repeat with mode `test`, a new state, CPU set 12–15 and fixture `test-target-discovery`. Run `check-edge-cases.py "$individual" "$paired" "$edges"` to reproduce the 25 small ELF comparisons covering loaded and discarded sections, fallback cases, compression, relocatable output and an invalid relocation offset.

The native timing confirmations use both frozen test schedules after the instruction studies. Each elapsed sample times the real `cargo +ohm` process through exit. Hashing and reset commands are outside that interval. Report a latency reduction only when both schedules meet the separately registered interval, randomization and source-direction gates. [Native timing plan](native-timing-plan.json)

The analysis reports paired geometric reductions and 95% bootstrap intervals stratified by source direction. The exact two-sided randomization test conditions on the third arm’s position within each block. Each of the three groups then has four blocks with two baseline-first assignments, giving 216 allowable label permutations.

`native-oracles.json` records independent native traces and each raw executable digest for the six arm/direction combinations in each workload. The normalized labels in that file remove the local checkout prefix from the Cargo package identifier. The measurement itself compares every unmodified executable against the native reference at its real path. `source-oracles.json` records every affected file in both directions. `relocation-census.json` records Wild's selected input archives and their hashes from a real CLI link. Of 4,551,713 debug relocations in that executable, 4,549,295 come from selected archive members. All 1,438,170 `.debug_ranges` entries and 337,592 of 340,095 `.debug_loc` entries have the eligible adjacent local-section representation.

The Wild source integration suite passed 668 native x86-64 cases and 183 library tests. All 24 hosted jobs in the Wild source draft stopped before checkout. Each job has the same action-pinning policy failure on its base. [Matching CI annotations](source-ci.json)
