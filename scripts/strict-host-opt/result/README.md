# Ruff’s host build override on strict Cargo

The default host opt-level 0 and the supported `CARGO_PROFILE_DEV_BUILD_OVERRIDE_OPT_LEVEL=1` ran in both orders on two independently provisioned Linux x86-64 workers. No other environment or source setting changed in the scored commands. Both used Cargo `761ea115605c34f11a1cd29afd68812c1e1359dd` (ELF `035e6810…`), signed Ohm 1.99.0-21 rustc `c79998a5`, its driver, its Wild linker, the locked 498 registry crates and Ruff `93526150`. The only source change on the performance path was the complete historical reversal of `32c5cd5d` in `ty_project`. [Registration](../PLAN.md) · [Native run](https://github.com/astral-experiments/ohm/actions/runs/41153340627)

```sh
cargo +ohm check -p ty_project --tests --locked --offline -j8 --message-format=json
```

| User instructions, billions | Order 0→1, default | Order 0→1, opt 1 | Order 1→0, default | Order 1→0, opt 1 |
| --- | ---: | ---: | ---: | ---: |
| Empty, original source | 493.755 | 1,031.484 | 493.661 | 1,031.503 |
| Historical edit | 19.442 | 9.488 | 19.464 | 9.488 |
| First unchanged | 16.580 | 6.924 | 16.582 | 6.940 |
| Second unchanged | 17.171 | 7.514 | 17.184 | 7.523 |
| Third unchanged | 16.580 | 6.924 | 16.582 | 6.915 |

Both pairs passed the registered screen on the first unchanged check, at **2.395× and 2.389×** fewer retired user instructions. The real edit took 2.049× and 2.051× fewer. The fresh build took **2.09× as many**. Each worker ran 28 native calibration commands across direct, fork, grandchild, duplicate branch, exec and one/two-thread loops before acquisition. Every hardware interval had complete coverage. The scored whole processes used a native inherited counter with no debugger, compiler wrapper or role-specific instrumentation. The sample consists of two pairs, with no population interval or wall-time claim.

Fresh steady target plus shared storage was 796.04/796.07 MiB on default and 824.91/824.86 MiB with the override, around 3.6% more. Changing an already populated default target to host opt 1 cost 993.343/993.243 billion instructions. The reverse cost 455.587/455.556 billion. Each switch made 219 Cargo artifacts dirty and left 1,588.41–1,588.47 MiB allocated across both profiles. These are unique allocated bytes over both roots, collected after fsync and reopened against GNU `du` and a complete device/inode/block ledger. The raw switch includes its ordinary build work. [Individual phase receipts](verified.json)

In the separate traced clean checks, each arm launched 304 full rustcs and 48 actual signed Wild linkers. On the unchanged checks both arms physically launched exactly the same three full rustcs (`build_script_build`, `ron`, `unicode_names2`), the genuine native Wild linker and the Unicode generator. Kernel argv confirmed that `ruff_unicode_names2`’s build.rs, `unicode_names2_generator` and `phf_generator` changed from host opt 0 to 1, while the target `unicode_names2` and `ty_project` remained opt 1. The two signed-rustc execution probes per default/opt profile grouping preserved debug assertions and checked integer overflow. The 114 build-mode units moved to opt 1. Both graphs had the same 333 distinct package/target/feature/mode identities. Five duplicated `run-custom-build` entries disappeared from the 338-entry default graph, with equal numbers of cold physical compiler/link invocations.

Every healthy check produced the same three complete generated sources. Each native arm accepted the genuine historical edit, rejected the independent invalid source with the same complete E0308, then returned free of errors after repair. A separate 18-command provider gate on worker 01 retained the actual build-script ELF, argument and loader evidence, both higher-priority DSO bodies and the returned readers. In both arms the same-inode/size/mtime DSO replacement switched actual reader output from 83 to 47. Malformation failed in Wild and removal restored 0. Every case matched its empty reference. The 83 and 47 generator ELF bytes were identical within each profile even though the observable generated Rust changed.

The measured knob applies to all host build dependencies and procedural macros. A package-only profile or rustc change would need its own measurements, including cold cost and same-target storage. No Ruff or toolchain source change is included.

## Offline verification

The original two GitHub ZIPs, their GitHub metadata, native generator/reader images, physical compiler argument records, original Cargo JSON and stderr, generated sources and all allocation/counter rows are included. From this directory run

```sh
python3 -IB reopen.py | cmp - verified.json
```

| Worker | Original GitHub artifact | ZIP bytes | SHA-256 |
| --- | --- | ---: | --- |
| `nsc-runner-r12m076u4qpkc` (0→1) | [13024615642](https://github.com/astral-experiments/ohm/actions/runs/41153340627/artifacts/13024615642) | 11,055,507 | `0d49318f0e0f71c5a9a3d3d516f2b2afc2877c9f2869317af15132c5a5df047f` |
| `nsc-runner-ohv5q037nqhs2` (1→0) | [13024490328](https://github.com/astral-experiments/ohm/actions/runs/41153340627/artifacts/13024490328) | 3,739,030 | `7784be71e32df63aaffdaa49aa012c93861ec35e193128095a00ff76510e68c6` |
