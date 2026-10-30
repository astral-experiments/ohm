# Rebuild the Ruff GNU AArch64 comparison from source

To rebuild the toolchains used for ohm-rust #283 and run the Ruff edit with each one, dispatch this workflow from a checkout authenticated to the Ohm repository.

```sh
gh-auto workflow run ci.yml --repo astral-experiments/ohm --ref charlie/qa-gnu-svc-source-rebuild
```

The first worker bootstraps Rust `d3538b42` with host and GNU AArch64 standard libraries. It verifies all 119 SDK files, then builds Cargo `c18e91b5` (#301) with the signed `-20` Cargo and the freshly built rustc at the same source, registry, target and compiler paths as the measured build. It runs the Cargo marker test. The compressed Cargo executable crosses between workers in this run.

The original Cargo contains OpenSSL's build timestamp at byte 4,387,448. Its generator uses `SOURCE_DATE_EPOCH` when present. The replay sets it to 1793374538, the timestamp read from the measured executable, when building Cargo. It compares the full Cargo hash, all 35 ELF sections and all 12 segments with that executable. To additionally build Cargo with the current clock at the same paths and retain both complete executables for comparison, pass `-f clock_control=true` when dispatching the qualification. [Original Cargo ELF inventory](./original-cargo-elf.json)

The first source reconstruction rejected a different Cargo ELF after its 119-file builder matched. A fresh diagnostic build with the system clock differed from the original at 25,260 bytes. The differences covered 24,080 bytes in `.rodata`, 935 in `.text`, 225 in `.rela.dyn` and 20 in the GNU build ID. The linker placed the OpenSSL string 26,136 bytes later. Pinning the clock reproduced all 50,945,080 original bytes and passed the marker reader test. [Initial rejection](https://github.com/astral-experiments/ohm/actions/runs/41127978316) · [Fresh pair of Cargo executables and build records](https://github.com/astral-experiments/ohm/actions/runs/41129270278/artifacts/13012932036)

Two further Linux workers bootstrap `8f42a1c1` (#282) and `6ae50e2d` (#283) separately. Both install the Cargo built by the first worker. Each worker checks the name, mode, length and SHA-256 of all 119 installed files against its measured SDK. Each starts from independent empty source, compiler build and Ruff directories. The two measured manifests differ in the rustc driver alone. The Git commits are reconstructed from their pinned public Rust base and checked-in Git objects. The source trees, public upstream LLVM key, backtrace submodule and stage-0 identities are checked. [Compiler sources](../source/identity.json) · [Cargo source](../../ohm-aarch64-versioned/sources.json) · [Original candidate enrollment](../evidence/literal-svc-ruff-cli/) · [Parent and builder SDK manifests](../../ohm-aarch64-portable-review/source/sdk-members.json)

Comparing both full Git trees to their published PR heads found one difference in each, `.github/workflows/ci.yml`. Cargo's source commit is the published PR head. [Parent rustc](https://github.com/astral-experiments/ohm-rust/pull/282) · [Patched rustc](https://github.com/astral-experiments/ohm-rust/pull/283) · [Cargo](https://github.com/astral-experiments/ohm-cargo/pull/301)

The normal Ruff command builds the historical PLE0643 fix and immediately rebuilds it, using the ordinary dev profile, 372 Cargo units and the locked dependencies. Each worker preserves its raw kernel executions. The verifier checks the original full rustc counts, the real Ruff link, the E0425 verdict on an invalid edit, and byte-for-byte agreement with the same toolchain's empty build after edit, repeat and repair. QEMU executes the resulting Ruff binaries on a starred tuple, a genuine out-of-bounds access and a valid access. This qualification collects no timing or instruction samples. [Ruff edit](https://github.com/astral-sh/ruff/commit/193984681ef7185c90b548c27b0ac6326908f2ec) · [Original paired measurements](../evidence/literal-svc-ruff-cli/)

The source run reproduced the full 119-file builder SDK and both 119-file measured SDKs. On the real edit and the first repeat, the parent invoked 19 full rustc compilations each time. The patched compiler invoked four and three, respectively, and one link-only rustc for Ruff on each command. Both toolchains still ran the host build-script linker and the GNU AArch64 Ruff linker. Each edited, repeated and repaired binary matched its own empty build byte for byte. Both toolchains rejected the invalid edit with E0425 and produced the corrected PLE0643 verdict under QEMU. [Source qualification](https://github.com/astral-experiments/ohm/actions/runs/41129270278) · [Recounted native results](./qualification-41129270278.json)

The source qualification downloads normal published bootstrap and CI LLVM components, the checksummed Ohm `-20` distribution, the checked-out Rust release ancestry, and Ruff's locked source packages. The only Actions binary input to the qualification is the freshly generated Cargo from the same dispatch. A changed builder or installed SDK member fails the byte-identity check and leaves its observed and historical hashes in `physical-cargo.json` or `physical-sdk.json`.

To independently check a completed source-only dispatch on Linux, set `source_run` to its numeric run ID and `qa_commit` to the expected source revision. The checker downloads only this run's original SHA-verified archives. It opens the complete Cargo ELF, reconstructs all three SDK manifests, and recounts the actual rustc and linker executions, typed Cargo rosters, QEMU responses and E0425 verdict from the raw records.

```sh
python3 -IB scripts/ohm-gnu-syscall/source-rebuild/reopen.py \
  "$source_run" "$qa_commit" "source-proof-$source_run.json"
```

## Repeat the instruction counts from a fresh source build

Record the QA revision and ask for the registered holdout. Substitute `gh` for `gh-auto` if that is your authenticated CLI.

```sh
qa_commit=$(gh-auto api 'repos/astral-experiments/ohm/commits/charlie%2Fqa-gnu-svc-source-rebuild' --jq .sha)
gh-auto workflow run ci.yml --repo astral-experiments/ohm \
  --ref charlie/qa-gnu-svc-source-rebuild -f phase=holdout
```

The workflow first repeats all three source builds and the two untimed Ruff histories. It transfers the verified parent SDK once and just the changed rustc driver from the patched worker. Each of 12 new jobs reconstructs and validates both SDKs before it runs the original `paired.py` with the registered counter and role order. The libraries are shared between SDKs when installed in each worker. Each compiler still gets its own fresh Ruff build directories.

The transfer was exercised separately with the three original, SHA-verified archives. Reopening the resulting two kits reproduced all 238 file hashes, sizes and modes and shared the same 118 inodes between the two SDKs. A mismatched run identifier was rejected. [Original parent SDK](https://github.com/astral-experiments/ohm/actions/runs/41081958994/artifacts/12989079541) · [Cargo](https://github.com/astral-experiments/ohm/actions/runs/41081958994/artifacts/12989289345) · [Patched driver](https://github.com/astral-experiments/ohm/actions/runs/41099028701/artifacts/12998240646)

Set `holdout_run` to the numeric ID of that dispatch. After it succeeds, run this from the QA checkout to verify the 12 pairs, reopen their 72 AArch64 ELF files and compute their intervals from the original clocks. The collector checks the run ID, source branch, exact QA commit and every expected source-build and pair artifact. Collect within two days, while GitHub still lists the temporary kit transfers. The resulting compact records can be recounted offline with their bundled verifier. [Registered orders, controls and endpoints](../registered-pairs.json)

```sh
python3 -IB scripts/ohm-gnu-syscall/evidence/literal-svc-ruff-cli/collect.py \
  --source-rebuilt --run "$holdout_run" --head "$qa_commit" "source-holdout-$holdout_run"
```
