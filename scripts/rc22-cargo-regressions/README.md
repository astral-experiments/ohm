# RC22 Cargo regression qualification

This manual, read-only packaging workflow compares the Cargo pinned by release PR #223 with its four-fix candidate on one source-built Linux SDK. The SDK uses stage1 Rust and rustdoc, release-profile Cargo with `all-static,ohm-defaults`, and the existing distributed Wild binary. The Rust source is `625207d26ce4449c9c95d871c88cfb50e904c09f`. The Cargo commits are `2554a1dfaf22474b360a4298883acf41f82bd78f` and `4591cf45cc10abb19d2456c40b99606e08167f29`. The exact native configuration, source trees, Wild and worker file hashes appear in `kit.py`.

## Enroll a completed source SDK

The source workflow is fixed to the first attempt of run 41212542603, job 124570376741, on private packaging commit `7bc72b798b019a9ec0de6eeea3bc22b783917b27`. Enrollment requires the Linux build, native reopening, and original artifact publication to have completed successfully. The source job is an independent prerequisite of all five tests. Darwin provider qualification has a separate verdict. [Source workflow](https://github.com/astral-experiments/ohm/actions/runs/41212542603)

For a local review, run from this OSS checkout. The output path must be new. The binder can use the producer's read-only original instead of downloading a second copy. It verifies the original ZIP, every source inventory entry and the complete bounded zstd/tar stream. Without `--zip`, the two compressed inputs live in private memory during binding.

```sh
d=scripts/rc22-cargo-regressions
python3 -IB "$d/media.py" bind 7bc72b798b019a9ec0de6eeea3bc22b783917b27 41212542603 /tmp/rc22-gnu-source-anchor.json --zip /absolute/path/to/original.zip
python3 -m json.tool /tmp/rc22-gnu-source-anchor.json
```

After review, replace the unbound `anchor.json` with those exact JSON bytes. The sole proposed enrollment change is that file. The bound document includes the real artifact ID, size and SHA-256, the three archive-member hashes, the two exact source-reader hashes, and the two worker binaries' release identities. Its `registration` object is the exact input to both regression workers. The manual workflow accepts the resulting reviewed Git commit and its dedicated branch on attempt one.

## Qualify the inputs and both workers

Each worker independently rechecks the original ZIP SHA-256, all tar member paths, types, bounds, modes and bytes. It invokes the producer's hash-bound `sdk.py reopen` before probing the installed native executables. Source and loaded GNU architecture, actual verbose version stamps, compiler-selected sysroot, pinned Cargo identity and stock Wild must all agree. Both role executables and the exact SDK remain separate immutable inputs. Only the acquisition steps receive a read credential for this private repository.

Four new standard Ubuntu jobs run `native_mounts.py outer` for shared, late, private and private-fallback scenarios with genuine mount namespaces. They open the historical common/shared observers at `f23a67771c625785cd70f58e9b46e8d26af3d317` and private observer at `786e5235c3faf04fcfde6beef6c2b91537d37696`.

One native 16-CPU Namespace job runs `ruff_recovery.py` on the complete real `cargo check -p ty_project --tests` fixture. It verifies an actual ext4 `/cache` mount, then checks at least 42 GiB available before creating a fresh case. Prior native jobs on this runner recorded `/cache` on `/dev/vdi`. This packaging profile advertises a 50 GB volume, so available bytes need measuring on every job. Only the freshly claimed case is removed after copying its packet. The worker checks both earlier and fixed Cargo in the same installation and target paths with the genuine error, warning, bad/repair visits, independent empty roots and a physical metadata reader. [Previous native filesystem](https://github.com/astral-experiments/ohm-cargo/actions/runs/41210902057/job/124565463712)

Each output ZIP includes `rc22-kit/{registration,qualified}.json` and `rc22-proof/`. The latter holds the source binding, raw worker streams, NUL-separated true argv, exit, filesystem evidence and the worker's own `packet/`. An incomplete packet records its failing stage. Every matrix row uploads independently.

Local source, archive and directory controls can exercise the unmodified SDK author's real decoder against a small physical format fixture. Its native runnable files exercise the decoder but cannot pass the official RC22 binding.

```sh
RC22_TEST_SOURCE=/absolute/checkout/at/7bc72b798b019a9ec0de6eeea3bc22b783917b27 \
  python3 -IB scripts/rc22-cargo-regressions/test_carrier.py
```
