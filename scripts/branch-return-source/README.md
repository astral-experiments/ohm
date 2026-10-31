# Source qualification for branch-return instruction accounting

This manual, read-only Linux job builds both x86-64 GNU stage1 compilers from source at the same absolute path. Full is the reviewed Rust #274 commit `c6fe8ecda65452c105f85367a009af80cbb5efbc`. Packed is its QA-only direct child `0afbeff303d3658bff52582d8f1a996d59e6c8ce`. Its seven-file binary Git diff exactly matches historical `b676a640c7..eb15cd3dc0`. Current compiler, standard-library and test tree identities are recorded in `roles.json`. The historical comparison and its 140 GiB local wall-clock registration have separate ownership.

The public Rust source and the prior Ohm transports materialize both original checkout ancestors. The 112-object role pack adds nine commits and changed source paths over the authenticated live base. Both checked-in `./x` builds request the host compiler, full standard library and rustdoc together. They use identical stage0 binaries, upstream LLVM key, native host, bootstrap path and flags. Each SDK uses the stock signed -21 Wild and the strict Cargo ELF from builder job 124388202956, checked against its independent native-source build receipt. The period during which the original Cargo ZIP remains downloadable is recorded by GitHub. The successful transfer contains the exact bytes as a durable local replay input once downloaded.

Both ordinary Rustup exposures must select their matching compiler, rustdoc, physical host libraries, strict Cargo and stock linker. Each runs the three filesystem tests, all eight or ten incremental cache tests and seven named run-make suites. These cover flag opt-out, corrupt tables, invalid native inputs and, on Packed, corrupt native objects. Each also runs an ordinary executable/test-inventory check, a successful and an invalid rustdoc input, the original six branch/provider controls and sixteen ordinary warm versus independent-empty native builds. Those exercise a higher-priority unbundled archive, a byte replacement or malformed input at the same inode/size/mtime, repair and removal. The selected archive must actually be opened by the emitted stock linker. Both physical SDK inventories must match at every member except the source-rebuilt driver and, if observed and reported, its source-matched rustdoc. The final transfer is restored from scratch twice before publication.

For a successful run, authenticate its exact head, each official ZIP ID, size and SHA-256 with the helper. Extract the verified SDK ZIP to a fresh transfer directory. Run the following from this source checkout using the values in the authenticated observation `receipts/qualified.json`.

```sh
python3 -IB scripts/branch-return-source/locate.py "$RUN" "$HEAD"
python3 -IB scripts/branch-return-source/restore.py "$TRANSFER" "$F_SDK" F --qa "$HEAD" --run "$RUN" --attempt 1 --manifest "$MANIFEST_SHA"
python3 -IB scripts/branch-return-source/restore.py "$TRANSFER" "$K_SDK" K --qa "$HEAD" --run "$RUN" --attempt 1 --manifest "$MANIFEST_SHA"
```

The SDK ZIP contains `F-sdk.tar.zst`, `K-delta.tar.zst` and `manifest.json`. The observations ZIP carries source hashes, original build and named test logs, actual compiler and linker identities, the complete per-file inventories, native observations, real executable outputs and both final restore receipts. A failing job preserves its raw observations separately. The job measures no Ruff workload.
