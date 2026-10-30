# Rebuild the Ruff GNU AArch64 comparison from source

To rebuild the toolchains used for ohm-rust #283 and run the Ruff edit with each one, dispatch this workflow from a checkout authenticated to the Ohm repository.

```sh
gh-auto workflow run ci.yml --repo astral-experiments/ohm --ref charlie/qa-gnu-svc-source-rebuild
```

The first worker bootstraps Rust `d3538b42` with host and GNU AArch64 standard libraries. It verifies all 119 SDK files, then builds Cargo `c18e91b5` (#301) with the signed `-20` Cargo and the freshly built rustc at the same source, registry, target and compiler paths as the measured build. It runs the Cargo marker test. The compressed Cargo executable crosses between workers in this run.

Two further Linux workers bootstrap `8f42a1c1` (#282) and `6ae50e2d` (#283) separately. Both install the Cargo built by the first worker. Each worker checks the name, mode, length and SHA-256 of all 119 installed files against its measured SDK. Each starts from independent empty source, compiler build and Ruff directories. The two measured manifests differ in the rustc driver alone. The Git commits are reconstructed from their pinned public Rust base and checked-in Git objects. The source trees, public upstream LLVM key, backtrace submodule and stage-0 identities are checked. [Compiler sources](../source/identity.json) · [Cargo source](../../ohm-aarch64-versioned/sources.json) · [Original candidate enrollment](../evidence/literal-svc-ruff-cli/) · [Parent and builder SDK manifests](../../ohm-aarch64-portable-review/source/sdk-members.json)

The normal Ruff command builds the historical PLE0643 fix and immediately rebuilds it, using the ordinary dev profile, 372 Cargo units and the locked dependencies. Each worker preserves its raw kernel executions. The verifier checks the original full rustc counts, the real Ruff link, the E0425 verdict on an invalid edit, and byte-for-byte agreement with the same toolchain's empty build after edit, repeat and repair. QEMU executes the resulting Ruff binaries on a starred tuple, a genuine out-of-bounds access and a valid access. This qualification collects no timing or instruction samples. [Ruff edit](https://github.com/astral-sh/ruff/commit/193984681ef7185c90b548c27b0ac6326908f2ec) · [Original paired measurements](../evidence/literal-svc-ruff-cli/)

Every dispatch downloads normal published bootstrap and CI LLVM components, the checksummed Ohm `-20` distribution, the checked-out Rust release ancestry, and Ruff's locked source packages. The only Actions binary input is the freshly generated Cargo from the same dispatch. A changed builder or installed SDK member fails the byte-identity check and leaves its observed and historical hashes in `physical-cargo.json` or `physical-sdk.json`.
