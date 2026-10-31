# Native Ruff linking and compiler migration

This unscored qualification uses the complete matching host standard libraries, stage1 compilers, strict Cargo `761ea115605c34f11a1cd29afd68812c1e1359dd` and published Wild from the successful native admission. The parent is Rust `c79998a5cd143c445a4b2528f20953b176a65c5d`. The candidate is product `7562c319cd9dbd3c1aa99a5797638d05c2026fff` transplanted to exact signed source tree `0d30133a68ccfb5771670ef5fee7720e1483f5dc`. `inputs/native-seal.json` names each Actions artifact ID, SHA-256, size and expiry, and the independently reopened qualification. [Native admission, attempt 1](https://github.com/astral-experiments/ohm/actions/runs/41157899149)

The source is unmodified Ruff `93526150df078af7dd8fc4226cdcc469539d2001`. Both commands use eight workers and the checked-in lockfile. All 498 registry archive checksums must match before either history. There are no user profile overrides, compiler wrappers, trust settings or extra Rust flags. Every worker runs two independent histories from empty build and target directories at the same absolute paths. The first uses an inherited hardware user-instruction counter around the ordinary Cargo command. The second collects actual kernel exec events and full argument vectors in a separate replay. Four measurements in each of seven process and thread shapes must pass a two-percent calibration bound. No PTRACE, correctness test execution or storage scans run inside the benchmark counter.

## The actual `ty_server` e2e binary

```
cargo +ohm test --no-run -p ty_server --test e2e --locked --offline -j8 --message-format=json
```

One fresh worker uses each compiler. After a cold and an unchanged run, reverse Ruff commit `4d6a7db787130c5a4a95bd835369babd78e4a1f6`, run the command and its first repeat, restore the actual edit, and run the command and its first repeat again. The complete eight-file diff implements notebook cell mapping, changes two real server requests, and adds a test and two snapshots. The reversed Ruff tree is `5bf3ecfe0aa39f6520ea215ec593e755a194a894`. The source helper verifies all original and reversed Git blobs, and preserves input mtimes over unchanged visits. [Original Ruff edit](https://github.com/astral-sh/ruff/commit/4d6a7db787130c5a4a95bd835369babd78e4a1f6)

Each valid run must return the real `crates/ty_server/tests/e2e/main.rs` executable. The physically observed released Wild must write that actual inode on reverse and restore. Each original and restored native inventory must contain one more test, discovered from the genuine `--list` output, than its reversed counterpart. Execute that notebook snapshot case when present and a neighboring stable control in every state, outside the hardware counter. Every history must match its own independent-empty test name set, actual outcomes and whole ELF bytes. In case of disagreement preserve both complete executables plus all section and program-header fields and content digests. A matching test list cannot mask a binary difference.

## The first `cargo check` after a full SDK replacement

```
cargo +ohm check -p ty_project --tests --locked --offline -j8 --message-format=json
```

Three fresh workers populate ordinary target and shared build roots, run once unchanged, and then replace the complete compiler installation at the same pathname. Every install makes fresh regular-file inodes and sets a fresh installation timestamp. Rustup's `ohm` alias stays at the same address. Each source-built install includes every enrolled compiler/runtime and standard-library member; its separate QA specimens are excluded. The packaged signed role uses the original `rustc`, standard-library and Cargo components from the official release archive before substituting the exact same strict Cargo as the other roles. All five roles use the same genuine Wild and Cargo bytes.

| Role | Installed product before and after | Natural `rustc -vV` expectation |
| --- | --- | --- |
| `stage-to-candidate` | Rebuilt signed source, then candidate | Exactly equal, with metadata epoch 1 then 2 |
| `stage-to-sham` | Rebuilt signed source reinstalled from the same bytes | Exactly equal, including metadata epoch 1 |
| `signed-to-candidate` | Packaged signed `-21`, then candidate | Different complete version strings, metadata epoch 1 then 2 |

Each role runs its first and second ordinary unchanged check immediately after installation. The next real edit reverses Ruff's `32c5cd5daba51d9c3da691c5b43afa6a7a4bb731` dependency change in `ty_project`. It compiles the affected consumer while its old suppliers can remain in the populated graph. Repeat, make a malformed edit that requires `E0308`, repair it, restore the original valid edit and repeat. Empty targets independently compile original, reversed, malformed and repaired inputs. Product failures remain in the record and later visits proceed, so an empty rebuild cannot turn a stale success into a pass. [Original Ruff edit](https://github.com/astral-sh/ruff/commit/32c5cd5daba51d9c3da691c5b43afa6a7a4bb731)

A fresh native rustc probe, in independent paths, identifies every active metadata issuer. On each successful historical check, decode the actual metadata stamp of every returned nonempty workspace `.rmeta`, compare all returned workspace metadata and generated Rust bytes with that state’s independent clean build, and verify the complete Cargo artifact inventory. If Cargo returns stale metadata, retain complete examples, the physical version envelopes, and the current compiler’s independent diagnostic when importing each example. For a normal bad edit require exit 101, terminal failure JSON and the exact primary `E0308` source span. An `E0514` on valid input is a failed migration, even if a later clean build succeeds. Merely observing an installed compiler version change is expected in the signed role.

The capture records naturally observed `rustc -vV`, `cargo -Vv`, inode and mtime, file roster, whole-file digests and actual Rust metadata epoch. Identity probes use separate Cargo homes, build directories and targets. The product target and shared ledgers must remain byte-identical across the install and these probes. After every visit, count allocated bytes once across *both* directories by `(st_dev, st_ino)`, corroborate with one GNU `du` invocation, and retain the complete file ledger. Installed SDKs, private readback copies and source inputs are outside that storage figure. Report first-upgrade instructions, physical full/link-only rustc and Wild executions, and allocated-byte change against the preinstall repeat. Report the second visit and restored steady state separately.

During the separate physical migration, inspect up to two largest complete `ty_python_semantic` incremental sessions before installation, after the first visit, and after repair. Retain sizes, SHA-256 and allocated blocks for `dep-graph.bin` and `query-cache.bin`, plus each 64-KiB chunk’s SHA-256 and actual length. The reader reports common unique full-block bytes, common partial final-block bytes, and matching bytes with multiplicity. Identical inodes are reported explicitly. Content similarity alone does not establish filesystem block sharing. If fewer sessions survive, record that absence.

## Rerun and readback

The dedicated `ci.yml` has `workflow_dispatch` only. The `panel` input chooses `migration`, `e2e` or `all`. Each role needs one fresh Linux x86_64 worker with eight CPU slots, working hardware counters, ptrace of its own child processes and at least 70 GiB free before the study. There is one observation per role. A speedup estimate for publication needs a separately registered replicated comparison.

The native acquisition helper also works with retained ZIP files after their Actions copies expire. From this QA checkout use an empty directory or an archive cache containing exactly the original `parent.zip`, `candidate.zip` and `compiler-native-admission.zip` files. It verifies their full digests and reopens each archive and every SDK member before installation.

```sh
python3 -IB scripts/mixed-generics-ruff/kits.py acquire \
  /tmp/ohm-native-kits /path/to/the/original-zips \
  scripts/mixed-generics-ruff/inputs/native-seal.json
```

For an independent readback, download only the role artifacts from the single enrolled execution to `receipts/mixed-ruff-ROLE` directories and pass the exact packaging head and numeric run ID. The reader recomputes hardware calibration, all allocated-block totals, effective SDK/physical tool identities, metadata epochs, real test inventories, generated source bytes and complete retained divergent executables. It preserves the failed role when one occurs.

```sh
python3 -IB scripts/mixed-generics-ruff/reopen.py \
  receipts all /tmp/mixed-ruff-result.json --head "$QA_SHA" --run "$QA_RUN"
```
