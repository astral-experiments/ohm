# Cargo check after a failed test build

This Linux qualification compares released Cargo `2d44bd4aa` and fixed
Cargo `58f94004f` using the same signed Ohm 1.99.0-21 compiler, rustc
`c79998a5c`. It uses Ruff `93526150d`, the reverse of the historical
`32c5cd5d` edit, and this ordinary check.

```sh
cargo +ohm check -p ty_project --tests --locked --offline -j8
```

The complete command emits 303 compiler artifacts on a successful JSON
visit, or 302 on either genuinely invalid source. The invalid sources
both return 101 under each Cargo. On the first ordinary repair in each
installation the source parent starts only Ron, succeeds and still emits
the previous E0308. The fix also starts the local ty_project test
compiler and clears the error. The next unchanged process starts only
Ron. The warning controls require the real named deprecation in both
human and JSON output. There are 21 visits per source role, including
independent empty targets and two different invalid source texts.

The candidate-built Cargo test executable ran its added repair case
against both physical Cargo executables at the same harness path. It
failed on the parent with the stale E0308 and passed on the fix. Three
neighboring healthy cutoff cases passed on each Cargo. The fixed
library's short/JSON mismatch unit passed separately.

## Upgrading an existing cache

Signed Cargo first failed on a source that removed the warning. Returning
to valid source promoted the old success fingerprint even as subsequent
processes continued to show the stale error and omitted the true warning.
The failure survives fully fresh zero-compiler visits in a separate
two-local-crate case. Replacing just Cargo corrected that case and
returned it to zero compilers with the real warning. On Ruff the already
poisoned source kept its original source hash and timestamps and its
previous fingerprint path. The first fixed visit restored the warning
and the next JSON and human checks compiled only Ron. The published
Ruff result includes the upgrade's ordinary one-time recompilation.

The first source-built test binary lacked the release bootstrap channel.
That specific opt-out identity gate failed. Old Cargo used
`debug/build/.ohm-split-…` and the unchannelled build used
`debug/deps/.ohm-split-…`. There were 338 missing fingerprints and 304
compiler executions with correct diagnostics. The forced and empty
stages following that failed assertion were not executed in this
installation. The default migration still used exactly the original
output path, and the original failed opt-out observation is preserved.
[First qualification run](https://github.com/astral-experiments/ohm/actions/runs/41142196660)

The bootstrap passes both channel and release version to Cargo.
Cargo's new build-directory layout defaults on when this saved channel
is dev or nightly. Both source arms of the separate control set
`CFG_RELEASE_CHANNEL=dev` and `CFG_RELEASE=1.99.0-dev`. Only the real
signed toolchain carries its official release label.
[Rust bootstrap](https://github.com/astral-experiments/ohm-rust/blob/c79998a5cd143c445a4b2528f20953b176a65c5d/src/bootstrap/src/core/build_steps/tool.rs#L262-L265)
[Cargo layout default](https://github.com/astral-experiments/ohm-cargo/blob/2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c/src/workspace/features.rs#L886-L890)

The matched-channel run passed all 19 visits. Replacing signed Cargo with
its same-source build reproduced the stale E0308 and compiled only Ron.
Replacing the parent with the fix started 303 Cargo units and one
memoffset/autocfg compiler probe. The 48 distinct native links used the
original signed Wild, identified by device, inode and hash. This is the
one-time cost on this graph. The next JSON and human visits compiled only
Ron and started no linker. With Ohm defaults disabled, signed Cargo, the
source-built parent and the fix used the same output path and started
zero compilers and zero linkers at both switches and the repeat.

Removing only the valid unit's required private metadata output (zero
bytes for this check-only test target) forced both Ron and the
ty_project test compiler to run. The replacement inode differed. The
freshly generated diagnostic matched the full typed warning from the
separate empty build. That independent empty visit ran 303 Cargo units,
one compiler probe and 48 links. Its repeat returned to Ron alone. All
repairs retained actual raw spans and the named warning. The verifier checks
compiler and linker counts plus the reported diagnostics.

## Replay

Run from this directory using Python 3.11 or newer.

```sh
python3 -IB verify.py
```

The verifier hashes the three transport packets, checks every retained
member, parses the original Cargo output and matches the actual exec
records and arguments to each binary and compiler. The physical signed
archive is 359,657,153 bytes with SHA-256
`6f550de85f95440a61b5bd1a9d2ab0528d4fcaf674fdc008f5e986d2138be6c4`.
The original CI ZIP digests and solid lossless raw-payload digests are
in `custody.json`. When available, the three original ZIPs may instead
be supplied as explicit arguments in the order Ruff, in-tree, and
matched-channel. No tests are executed by the replay.

The first matched-channel submission stopped at a Python import before
acquiring a toolchain. Its successor resolves the QA module explicitly
under isolated Python. Both run IDs remain distinct.
[Import-only stop](https://github.com/astral-experiments/ohm/actions/runs/41143333561)
[Matched-channel acquisition](https://github.com/astral-experiments/ohm/actions/runs/41143428563)
