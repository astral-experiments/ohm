# Native qualification after Ohm 1.99.0-23

Both native hosts passed with Rust `c3aa3a605e56878669c745a9dd3ba09c9ccfa1ef` and Cargo `abc70d60a6fd89c10d5f65cf85820d9b78d5affe`. The same manifest came out of both source reconstructions. Its SHA-256 is `8d53d8e89674da89229d4f0df60e7a8394ffd82a790bcfb7960ba040dcb399a5`. Both passed the release source verifier from packaging `b4dab2cb`. The run built an all-static ThinLTO Cargo and an optimized stage-1 rustc, rustdoc and standard library with the profiler runtime. Its signed control used the published -23 toolchain. [Native jobs](https://github.com/astral-experiments/ohm/actions/runs/41662909910) · [Rust source](https://github.com/astral-experiments/ohm-rust/commit/c3aa3a605e56878669c745a9dd3ba09c9ccfa1ef) · [Cargo source](https://github.com/astral-experiments/ohm-cargo/commit/abc70d60a6fd89c10d5f65cf85820d9b78d5affe)

| Reopened outcomes on each host | Linux x86-64 | macOS arm64 |
| --- | ---: | ---: |
| Direct inputs, include checksums, doctests, native clients and Cargo-only upgrades | 112 | 112 |
| Requested metadata stubs for native libraries and their consumers | 70 | 70 |
| Coverage source rendering and explicit source remaps | 16 | 16 |

Signed -23 failed two consecutive warm rustc calls for each of `rlib` and `dylib` with `-Zembed-metadata=no`. With the fix, both libraries built twice warm and a new client linked against each and printed 17. Real Cargo build-script edits and deletion of the native product also exercised stub generation. The fixed compiler rejected E0308, picked up a real behavior change to 29 and matched an independently empty build. Darwin preserved its stable CGU member names. Linux compared the same object bytes under the normalized random archive-member suffix. [Metadata fix](https://github.com/astral-experiments/ohm-rust/pull/350)

Signed Cargo recorded two executions but could not render the source from the active checkout. The fixed Cargo rendered the actual line with count two through an environment flag, a Cargo profile and `cargo rustc`. It also honored successive declared source prefixes. Changing only Cargo in the same warm target repaired both results, with the original signed compiler and libraries. The independent verifier decoded 36 real raw profiles and reproduced all 18 native profile merges byte for byte. [Coverage fix](https://github.com/astral-experiments/ohm-cargo/pull/438) · [Profile remap fix](https://github.com/astral-experiments/ohm-cargo/pull/439)

## Ruff's locked Ron

The Linux SDK from the native run also compiled a path copy of the published `ron 0.12.0` with `cargo +ohm -Zembed-metadata=no build --locked --offline`. The fixture verifies the eleven archive checksums from Ruff commit `bfa2407e`, every copied Ron Rust source file and the actual `default,std` features. Giving Ron a path enabled incremental compilation. Signed -23 failed both its unchanged rebuild and repair of a removed rlib. The exact integrated SDK completed both, with a physical Ron compile in each. All 157 repaired native member bodies matched the donor, and all 157 independently clean bodies matched the cold build. The old client printed `[17, 29]`, the invalid edit failed with E0308, and the edited and clean clients printed `[17, 31]`. Official Rust/Cargo 1.99.0 also repaired the deletion and skipped the unchanged Ron compile. The two native-host tests above use ordinary Cargo and direct rustc separately. [Ruff lockfile](https://github.com/astral-sh/ruff/blob/bfa2407e98ee1343caeefd02b4b69043509baa8c/Cargo.lock)

From the packaging repository root on x86-64 Linux, reopen the preserved real clients, original compiler messages and every native archive member with Python 3.12, GNU ar and zstd.

```sh
e=scripts/ruff-combined-apple/evidence-41662909910
proof=$(mktemp -d)
tar --zstd -xf "$e/ron/originals.tar.zst" -C "$proof"
python3 -IB "$e/ron/check.py" "$proof" signed-archives fixed-archives stock-archives > "$proof/ron.json"
cmp "$proof/ron.json" "$e/ron/verified.json"
```

To repeat the actual ordinary Cargo builds, give each role a private Rustup home whose `toolchains/ohm` points at that physical SDK. The preparation step reads the exact Ruff object, verifies and extracts its registry archives, then uses the signed Cargo to resolve the small project offline. Point `--registry-cache` at a Cargo `registry/cache` directory to use already downloaded packages.

```sh
python3 -IB "$e/ron/prepare.py" "$proof/work" "$RUFF_CHECKOUT" "$SIGNED_RUSTUP_HOME"
python3 -IB "$e/ron/replay.py" "$proof/work" signed "$SIGNED_RUSTUP_HOME" current
python3 -IB "$e/ron/replay.py" "$proof/work" fixed "$FIXED_RUSTUP_HOME" current
python3 -IB "$e/ron/replay.py" "$proof/work" stock "$STOCK_RUSTUP_HOME" current
python3 -IB "$e/ron/check.py" "$proof/work" signed-current fixed-current stock-current
```

## Native originals and reruns

The two ZIPs in this directory are the unmodified native-host verdict artifacts. The coverage verifier checks their recorded SHA-256, source and tool identities, physical profiles, execution counts and declared file paths. Install official `llvm-tools-preview` for Rust 1.99.0 on Linux and set `OHM_LLVM_TOOLS_SYSROOT` to its sysroot when installed outside the default Rustup location.

```sh
python3 -IB "$e/verify-coverage.py" --zip "$e/integrated-release-verdicts-x86_64-unknown-linux-gnu-41662909910.zip" --artifact "$e/x86_64-unknown-linux-gnu-13245290399-artifact.json" --host x86_64-unknown-linux-gnu --output "$proof/linux.json"
python3 -IB "$e/verify-coverage.py" --zip "$e/integrated-release-verdicts-aarch64-apple-darwin-41662909910.zip" --artifact "$e/aarch64-apple-darwin-13244740112-artifact.json" --host aarch64-apple-darwin --output "$proof/macos.json"
```

While the original job binaries are in Actions retention, `intake.py` checks run identity, artifact size and digest before extracting the two Cargo executables and verdicts. The Linux SDK has a separate intake. Each receipt records the full native hashes.

```sh
head=1082c4561804649509970095a015daa656dd4fc4
python3 -IB "$e/intake.py" 41662909910 "$head" verdicts "$proof/host"
python3 -IB "$e/legacy-reopen.py" 41662909910 "$proof/host"
python3 -IB "$e/reopen-stubs.py" 41662909910 "$proof/host"
python3 -IB "$e/intake.py" 41662909910 "$head" sdk "$proof/sdk"
```

The acquisition workflow is pinned to the separate QA branch below. It checks the requested commit before rebuilding both platforms. The first combined attempt stopped on a source-factory checkout identity mismatch, before compiling a product. The qualified run restored the required factory and checked out the current verifier separately.

```sh
gh-auto workflow run ci.yml -R astral-experiments/ohm \
  --ref charlie/qa-rc23-integrated-green-stub-20261103 \
  -f reviewed_head=1082c4561804649509970095a015daa656dd4fc4
```
