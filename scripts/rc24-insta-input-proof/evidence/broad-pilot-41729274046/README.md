# Broad registry input retention in the published Linux -24 toolchain

The three-line Cargo change rebuilt one fewer crate during an unchanged Ruff test build. It also increased the cost of an unchanged check and build on both fresh workers, crossing both registered stop thresholds. The larger confirmation was withheld for this candidate.

The real workflow was `cargo +ohm test -p ty_project --lib --no-run --locked --offline -j4` after applying Ruff #29604. All counts below cover retired user instructions for the entire ordinary Cargo process tree. The two arms used the same published Linux -24 rustc and Wild. The separately built all-static optimized Cargo executables were the release source abc70d60a and its child 9e279eed9. These comparison binaries use the matched source-build configuration recorded in the receipts.

| Fresh runner and order | Parent → candidate, unchanged test build | Unchanged check | Unchanged build |
| --- | ---: | ---: | ---: |
| Parent then candidate | 53,002,463,836 → 12,761,282,092 | 998,013,522 → 1,149,679,483 | 461,839,827 → 547,653,758 |
| Candidate then parent | 53,000,276,089 → 12,762,274,117 | 998,022,344 → 1,150,023,653 | 461,796,497 → 547,639,998 |

A separate kernel trace on each installation observed real full rustcs for `insta` and `ron` on the parent, and `ron` on the candidate. The edited, settled, repaired and independently empty programs matched within each arm. Their native test suite grew from 77 to 78, including the new test. The same-size malformed Insta source yielded E0308 on two consecutive commands on each installation. `verified.json` also reports both repeated check/build controls, cold and edited instructions, successfully run oracles, typed rosters, translated footprints, and raw kernel argv hashes.

Run this from the checked-out directory. It reopens the two original GitHub archive digests, verifies both counter calibrations, obtains all 48 counters from their hardware records, decodes each native process from its literal NUL-delimited argv and thread epochs, and reconstructs the native and error checks from raw Cargo output.

```sh
python3 -IB reopen.py --write /tmp/ohm-insta-original-broad.json
cmp /tmp/ohm-insta-original-broad.json verified.json
```

[Original admission and raw workers](https://github.com/astral-experiments/ohm/actions/runs/41729274046) · [Frozen workload and thresholds](https://github.com/astral-experiments/ohm/tree/d40f789799162a7e58bd96826a5f9caa3bdc008d/scripts/rc24-insta-input-proof).
