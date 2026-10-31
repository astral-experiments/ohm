# What fraction of this unchanged GNU Ruff command runs inside stock Wild?

On one native x86-64 GNU host, count the whole ordinary Cargo command and each of its two stock Wild processes with all descendant threads. Report each fraction, the unobserved-by-Wild remainder, and the upper bound on whole-command improvement if the two linkers cost zero. This diagnostic cannot establish the cost of validating native search, a product speedup, or wall time.

## Locked inputs and previous physical observations

Use Ruff `7b13f01ba1569887a25670820764b24c206da8e5`, its complete lockfile and all 505 archived checksums. Use the 2,473-member GNU source kit from run 41212542603, artifact 13046543047, and its release-profile fourfix Cargo. Recheck the Rust source and physical driver, Rustup selection, sysroot, actual rustc, Cargo and stock Wild. The new unit graph must match the prior 390-entry canonical roster. That prior job used a different compiler and Cargo. [GNU SDK source run](https://github.com/astral-experiments/ohm/actions/runs/41212542603) · [Historical 390-unit structural run](https://github.com/astral-experiments/ohm/actions/runs/41227421360)

| Subject | Git revision or SHA-256 |
| --- | --- |
| Rust | `625207d26ce4449c9c95d871c88cfb50e904c09f` |
| Cargo | `4591cf45cc10abb19d2456c40b99606e08167f29` |
| libdriver | `056d6ed56a45e6997be1a79aa4e96c7bdbaced2530aad04353c8bc11f8ed4e6c` |
| Stock Wild | `0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5` |

The earlier same-host fourfix witness had 388/390 fresh, two genuine link-only rustcs, two Wild links, byte equality with both own-empty products and 96/96 tests. Its native search control changed both ELF NEEDED entries twice, rejected a same-stat malformed file (Cargo 101), repaired both and restored the original files after removal. The independently empty changed and malformed controls agreed. Their respective result digests are `feee800a4d71a85180c9e4e1786a10b286b36eb746b692b0e534277c58000c2c`, `ff7dc53aa84cbbac0a6f20630022270b770ecfefa8f666eb99d0fa124816699b` and `84872b31212d4f0b5036362da9bbd75693df208197705603cd8108a4f7181098`. None contains a Wild retired-instruction measurement.

## Collection

Use one checkout, mount namespace, SDK, four pinned CPUs, and fixed target/build directories for every visit. Require 32 GiB free on entry. No compiler/linker wrapper, cache opt-in, RUSTFLAGS, ptrace on cold builds, or force flags. Authenticate the two independently empty ordinary builds by parking only the task-owned first target/build then recreating both under their original names. Both must have 390 dirty typed units and produce the same complete CLI and test executable. Run and check both outside every counter, including the complete 96-test inventory and two genuine subprocess cases.

```sh
cargo +ohm test -p ruff --test integration_test --no-run --locked --offline -j4 --message-format=json
```

After the second empty build run four immediately matched pairs on this warm history. The fixed order is observed/plain, plain/observed, plain/observed, observed/plain. No optional selection or exclusions. The plain visits run under the whole-command counter alone. The observed visits use kernel task and successful exec stops, with a whole counter and a new inherited counter at each identified stock Wild exec, before its first userspace instruction. Capture the exact dev/inode, full argv and process family. Require the actual Cargo, two distinct link-only rustcs and saved recipes, corresponding cc and collect2, physical Wild, both actual distinct output names, original zmij/serde_json rlibs and gcc_s, 388 fresh and both complete healthy products. Accept only disjoint Wild subtrees. Include the linker process and all of its inherited descendant work. Rustup, Cargo, rustc link-only, gcc, collect2, and preprocessing remain outside those subtrees. Kernel task tracing and perf inheritance apply to this authenticated workload; the observer does not prohibit arbitrary hostile CLONE_UNTRACED workloads.

Each FD must open a hardware userspace retired-instruction counter with kernel/hypervisor excluded. Require a full 24-byte read, positive instruction and enabled time, and running time exactly equal to enabled time. The whole starts at the initial Rustup exec. Subtree counters start at the two Linux exec stops. First run the inherited 28 whole and 8 nested calibrations. Run eight additional tests against the actual narrowed selector, with zero/2M/zero/8M-iteration counts in each mode and independently known assembly slopes for siblings, whole and remainder. Require each within 2% and the measured whole calibration within 2% of plain. Exercise two actual small GNU stock-Wild links, check both native return values and challenge the identity and ancestry reader. The normal Ruff whole count must agree with each paired observer visit within 3% of the smaller whole. Otherwise preserve partial records and decline the share.

Report raw integer counts, each observed Wild share, summed share, remainder and the bound W/(W − L1 − L2) for every pair. Show sensitivity to the matched plain denominator separately. A summed share below half on both denominators in all four pairs rules out 2× from these two linkers alone on those observations. Above half merely admits another experiment. No inference to another compiler, Cargo pin, host, edit, or mode.

After counters close, insert a real earlier gcc_s provider into the genuine psm search path, overwrite it with another SONAME maintaining inode, size and nanosecond mtime, then write a malformed script with the same tuple, repair and remove. Require two actual stock Wild writes in each visit, changed full ELFs on both good substitutions, a genuine missing input and Cargo 101 on malformed, and complete restoration on removal. The full native tests run out of band. Reopen retained compressed executable bytes, inspect the ELF dynamic dependency and compare the complete NEEDED table with its own empty result.

## Reproduction

From this branch run `RUNNER_TEMP=/tmp python3 -IB scripts/gnu-wild-share/test_share.py` for the synthetic reader/refusal tests. One reviewed manual workflow attempt on `charlie/qa-ruff-gnu-wild-share-20261031` accepts only its exact HEAD as the `reviewed_head` input. On a host with denied PMU or ptrace, it records the refusal and emits no workload estimate. With the downloaded artifact and the observer checkout listed in ci.yml, run `python3 -IB scripts/gnu-wild-share/verify.py path/to/receipts path/to/observers/scripts/gnu-example-ceiling`. The earlier 28+8 calibration used the original selector on two independent hosted GNU boots. This carrier requires fresh checks of the narrowed selector. [Historical calibrated hardware cohort](https://github.com/astral-experiments/ohm/actions/runs/41178440891)
