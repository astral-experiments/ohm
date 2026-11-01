# Native dep-graph slot recovery

The Rust subject is `c0b318301965619c2cbd4b261ff3de84fac6831b`, a direct child of `c5178286c2661c22ef4ed304d7213589483548ee`. The 1bc7 GNU distribution and Darwin instrumented producer use the complete c517 parent source tree. The case concerns a saved row with a null kind, a second writer to the same slot, or a destination beyond the declared node space. The third case previously panicked two lines earlier. The original Apple run retained the compound panic message but lost its mapping, so its particular row and its producer remain unknown. [Original Darwin job](https://github.com/astral-experiments/ohm/actions/runs/41256793646/job/124701560586)

`source.pack` carries the exact Git history and complete tree delta from the already authenticated distribution source. Its 3,156 objects occupy 1,921,035 bytes. A fresh independent bare repository containing only 4,314 boundary objects, with neither the child nor its tree present, imported the transport with `git index-pack --strict` and reproduced the full source catalog. Production Rust changes only the eager persisted graph reader and its two callers. The checked-in `incremental-missing-query-cache` regression also exercises recovery with a corrupted companion cache, unusable CGUs, required-load and normal E0308 diagnostics. The format, writer and ICH verification stay compatible. The valid path retains a single indexed pass. Its instruction count has not been measured.

## Two native workers

The manual workflow accepts only this QA branch, its exact reviewed head and attempt one. GNU uses a 16-core runner with enough space to install the 79 authenticated host files from job 124701560401. Darwin uses the original 3,070-path instrumented stage2 from job 124729729200 as the old producer. Both authenticators verify the original run, job, Git source, official ZIP size and digest, inner inventory and physical tools. Build and native phases have a 230-minute job deadline. The native fixture requires at least 4 GiB free before each of its three suites. [GNU distribution](https://github.com/astral-experiments/ohm/actions/runs/41256793646/artifacts/13064288126) [Darwin instrumented producer](https://github.com/astral-experiments/ohm/actions/runs/41266309274/artifacts/13069826622)

GNU uses upstream bootstrap to run the exact source regression on its native stage1. Darwin first uses the unchanged release coordinator and source-pinned rustc-perf at `0a054b0e` to build the candidate's instrumented stage2 and run the nine natural benchmarks with four collector workers. Its supervisor stops only at the positive end of the rustc profile group, as in its already qualified predecessor. The worker requires the full 27 benchmark/profile rows and a nonempty merged profile and escrows the first result before diagnostics. It verifies the actual stage2 and Cargo4591 revisions and native profiling sections, then runs fresh Diesel Opt through all four scenarios. The collector can legitimately skip rustc in an unchanged scenario. Darwin's separate real source regression runs at stage1 after all observations of the instrumented stage2. A successful natural dataset establishes that this run completed. Only the deliberately damaged sessions determine how this candidate handles the disputed slots. [Unchanged coordinator and preserved original reader](https://github.com/astral-experiments/ohm/tree/e8c4c99286652f27929290e417ff269e32d0bbd5/scripts/darwin-pgo-diesel)

Each native job takes three disjoint small histories. The old tools must reproduce the two distinct panic sites and remain able to load a genuinely reordered graph. The candidate must report corruption and recover from all three damaged slots, reject `-Zassert-incr-state=loaded`, preserve the E0308 source diagnostic on an invalid edit and reproduce its own independently clean 83 executable on repair and retry. A real warning must survive successful cache use. The stage matrix damages the build checkpoint, canonical graph, or both, with independently unusable companion files. A usable checkpoint intentionally bypasses an invalid canonical body. The full source, warnings, errors, physical graph and query bodies, work products and distinct executables are retained.

The third history uses the old binary to write A and its build/check checkpoint. The candidate must demonstrate actual loaded reuse on an intact, physically reordered A and cold recovery on the damaged ones. These calls use the original rustc-perf version overrides and one private physical sysroot directory whose files point to the currently selected toolchain's authenticated inputs. This isolates matching-format producer/reader semantics. The first two histories use each compiler's ordinary version and sysroot. In the devbox rehearsal, two authentic source-compatible compilers under separate sysroot directories rejected the differing saved option hash. Using one real directory let the second compiler load the old session, print 17, accept the edit to 83 and match its own full cold executable at both revisions. Sharing the old standard library with the second binary instead gave E0514.

## Reopen

The following runs without contacting a remote service. `parent-graph.gz` contains an authentic GNU parent graph, raw SHA-256 `cb48adbfc616ceed962d29b17f2171aa6d22788c703a6bffbddeb2745ce18220`. The test moves a genuine variable-length complete record to the front and checks all three independent corruptions both before and after that relocation. The release compiler itself also accepted a complete record permutation with indices 1,0.

```sh
qa=/home/dev-user/code/oss/ohm-package-qa-rc22-reject-node-slots-20261101/scripts/dep-graph-slots
raw=/home/dev-user/.cache/ohm-rc22-diesel-depgraph-20261101/slot-containment-v1
(cd "$qa" && shasum -a 256 -c SHA256SUMS)
python3 -IB "$qa/test_slots.py" --receipt "$raw/qa-parent-1"
python3 -IB "$qa/qualify.py" catalog /home/dev-user/code/oss/ohm-rust-reject-invalid-node-slots-20261101
```

On the enrolled target, reopen extracted `slot-native-<host>` using its unmodified original files. The optional `--bytes-only` produces a distinct nonexecuting readback on other hosts.

```sh
python3 -IB "$qa/qualify.py" read "$packet/slots-previous" --role parent
python3 -IB "$qa/qualify.py" read "$packet/slots-candidate" --role candidate
python3 -IB "$qa/qualify.py" read "$packet/slots-previous-to-candidate" --role candidate --mixed
```

The devbox receipts establish the prior failures and existing cold fallback. They do not establish that a rebuilt candidate passes or that the original native writer was faulty.
