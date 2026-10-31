# The actual Ruff test executable and three compiler installations

Both compilers passed the original `ty_server` link qualification. The migration qualification failed its whole-metadata comparison in all three roles, including the identical compiler reinstall. This receipt keeps that result. Both workflows used the qualified native SDKs, exact strict Cargo and published Wild and ran 100 normal Cargo commands at packaging revision `9e125aab30ec25c421a1c2c6e97fac34e7248517`. [Real test executable](https://github.com/astral-experiments/ohm/actions/runs/41159614839) · [Same-path migrations](https://github.com/astral-experiments/ohm/actions/runs/41159617280) · [Native compiler admission](https://github.com/astral-experiments/ohm/actions/runs/41157899149)

## What the real edit linked

The full eight-file reverse of Ruff `4d6a7db78713` changed the native e2e inventory from 200 to 199 by removing `notebook::cells_after_cell_magic`. Restoring the edit restored precisely that test. Both compilers produced the same whole ELF for each state across their two histories and their own independent empty builds. Native snapshot checks agreed. In each compiler's separate kernel trace the released Wild linked the actual returned e2e on both edit and restore. [Ruff edit](https://github.com/astral-sh/ruff/commit/4d6a7db787130c5a4a95bd835369babd78e4a1f6)

## What changed on the first check after installation

Each worker made 24 visits. Every valid input succeeded. Every malformed input produced Cargo exit 101, terminal failure and `E0308` at the introduced type error. The real edit and repair agreed with independent clean diagnostics, generated Rust and returned unit inventories. Every successful check returned 32 workspace metadata rows with the same unit keys, one empty test row and 31 actual metadata files from the active compiler. Neither eligible upgrade returned an epoch-1 file under the epoch-2 compiler. The original byte-equality gate still failed in 14 historical-versus-clean comparisons per role.

The second ordinary check produced the same 32 complete metadata digests as the first ordinary check in every role. Independent empty cold histories **before installing anything** already disagreed on 24 of the 32 metadata hashes in all three roles, including both the signed compiler and the source-built parent. All 32 cold-pair keys, sizes and compiler stamps agreed. The independent empty reversed and repaired builds were also on the same source bytes. Those differed in 22 complete hashes on the signed-to-candidate role, four on stage-to-candidate and 22 on the sham.

The 1,024-byte original metadata envelopes show concrete differences. In the identical compiler's `ruff_diagnostics`, the first changed byte in the two cold builds is at offset 969, in the 16 bytes following the encoded `serde` dependency name. The following Cargo filename is unchanged. Other files expose the analogous difference after `char_str`, `ruff_python_ast` or `ruff_text_size`. The metadata schema encodes the dependency hash there. The receipts retain complete file sizes, SHA-256 digests and the actual headers. Ordinary current-epoch files were not archived in full, so this evidence does not localize every differing byte. [Metadata record](https://github.com/astral-experiments/ohm-rust/blob/c79998a5cd143c445a4b2528f20953b176a65c5d/compiler/rustc_metadata/src/rmeta/mod.rs) · [Dependency encoder](https://github.com/astral-experiments/ohm-rust/blob/c79998a5cd143c445a4b2528f20953b176a65c5d/compiler/rustc_metadata/src/rmeta/encoder.rs)

The preinstall state and first two postinstall totals below come from the separate kernel-exec history. Each total counts physical allocated blocks once across target and shared, excludes SDKs, and agrees with an independent GNU `du`. Full ledgers remained byte-identical across each installation and private identity probe. In every role the product path stayed `/home/runner/work/_temp/ohm-mixed-rust-ruff/installed/current`. Both stage installs had identical natural `rustc -vV`. The byte-identical sham replaced all 66 regular file inodes and updated their mtimes. The signed compiler had a different natural version string. The projection includes the actual old/new compiler, driver, standard library, strict Cargo and Wild device/inode/bytes, plus the target and shared root inodes.

| Complete SDK replacement | Preinstall allocated bytes | First check allocated bytes | Second check allocated bytes |
| --- | ---: | ---: | ---: |
| Published signed `-21` to candidate | 833,777,664 | 1,678,782,464 | 1,678,798,848 |
| Rebuilt signed compiler to candidate | 845,160,448 | 1,217,495,040 | 1,217,511,424 |
| Identical rebuilt signed compiler | 845,152,256 | 1,229,201,408 | 1,228,865,536 |

On the first check every role rebuilt all 303 Cargo units. The registry supplied 222 libraries, 28 build scripts, 17 proc macros and one rlib/cdylib. The workspace supplied 32 library/test units, two build scripts and a proc macro. A separate rustc reading stdin for `memoffset`'s `autocfg` probe makes 304 physical compiler processes. Released Wild ran 48 times. The second check ran three physical rustcs and one Wild. The original ZIPs retain the full compiler arguments. The projection classifies every physical compile by source, crate type and effective optimization level. The instruction counts remain original diagnostics from a failed admission and do not establish an upgrade speedup.

Only the signed-to-candidate role retained two completed `ty_python_semantic` incremental sessions at once. Their 181,108,154-byte and 181,107,877-byte dep graphs shared zero aligned 64-KiB content hashes. Their 44,928,783-byte and 44,928,281-byte query caches also shared zero. The old files remained on their original inodes through repair. The other roles retained one completed session per observed state. Original chunk arrays and full/partial overlap calculations are in the Actions ZIPs, and the resulting comparisons are in the projection.

## Reopen

From this directory run the small verifier. It rechecks all per-unit comparisons against the 520 retained metadata envelopes and verifies the complete phase counts, emitted diagnostics, disk allocations, actual test inventories, recorded native tools and both original workflow rulings.

```sh
python3 -IB verify.py
```

`originals.json` pins the workflow head, attempt in the original registration, numeric artifact IDs and full ZIP SHA-256 digests. `original-member-index.json.gz` records every original member's size and SHA-256. To redo the independent physical review, provide the seven unmodified ZIPs. The original verifier and `project.py` independently reread them. The container names in the example match the original Actions artifact names plus their IDs. These Actions files have finite retention. A retained checksum-matching copy works offline.

```sh
mkdir -p /tmp/ohm-ruff-originals
python3 -IB - /tmp/ohm-ruff-originals <<'PY'
import json, pathlib, subprocess, sys
out = pathlib.Path(sys.argv[1])
for name, record in json.loads(pathlib.Path("originals.json").read_bytes()).items():
    artifact = f"repos/astral-experiments/ohm/actions/artifacts/{record['id']}/zip"
    with (out / (name + ".original.zip")).open("wb") as f:
        subprocess.run(["gh-auto", "api", artifact], stdout=f, check=True)
PY
python3 -IB verify.py --originals /tmp/ohm-ruff-originals
```

`projection.json.gz` contains all per-phase workspace keys, sizes, issuers, complete file SHA-256s, original/empty pair comparisons, install identities and physical storage. To project a different local copy of the same originals, run `python3 -IB project.py /tmp/ohm-ruff-originals /tmp/ohm-ruff-projection.json.gz`. The uncompressed canonical JSON SHA-256 is `51e3f8d6216dff5ac5ed894909711e28899e2860da8c043286670d5c01acde63`.
