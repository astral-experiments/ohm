# Native links on the released Cargo lineage

The experimental Cargo at `fd55a13d` preserves the released zero-compile Unicode repeat and accepts the newer GNU AArch64 dep-info marker. It inherits the released Cargo's limitations with an older compiler. This integration is unsuitable for a release that requires the strict native-provider behavior of Cargo #293. [Linux Unicode builds](../released-unicode-integration/) · [Apple Unicode builds](./apple-unicode/) · [Exact Cargo source and binary](../../release-reader/)

On x86-64 Linux, each of four toolchains cross-built the ordinary Ruff CLI for GNU AArch64. The real Ruff edit fixed PLE0643 on an indexed tuple containing a starred value. Every edited, repeated and repaired program matched its independently empty build byte for byte, and QEMU returned the intended lint results. An invalid Rust edit produced E0425 in all four configurations. [Ruff edit](https://github.com/astral-sh/ruff/commit/193984681ef7185c90b548c27b0ac6326908f2ec) · [Original builds](https://github.com/astral-experiments/ohm/actions/runs/41109319369)

| Cargo | Compiler | Full compiles on edit | Full compiles on repeat | Link-only rustcs, edit / repeat | Ruff executable links, edit / repeat |
| --- | --- | ---: | ---: | ---: | ---: |
| Signed `-20` | Register-comment recognition | 22 | 22 | 0 / 0 | 1 / 1 |
| Signed `-20` | Plus literal `svc 0` recognition | 22 | 21 | 0 / 0 | 1 / 1 |
| Integration | Register-comment recognition | 17 | 17 | 0 / 0 | 1 / 1 |
| Integration | Plus literal `svc 0` recognition | 2 | 1 | 1 / 1 | 1 / 1 |

Only the Rust driver and the selected Cargo varied in this four-way comparison. The remaining 117 SDK files matched. The signed Cargo executable comes from the shipped Linux `-20` package. Both rustc drivers in this table are experimental. Counts come from kernel execution records for the same 372-unit Cargo graph. This comparison measured the work performed. The separate paired experiment using Cargo #301 supplies instruction counts.

With the newer writer, all 108 direct and transitive native-provider builds and all 84 reader upgrade/downgrade builds matched independent empty controls, including changed, removed and malformed archives. An additional 12 Cargo builds exercised proc macros that track real paths with either reserved name. The integrated reader treated each real path as an input.

With the old writer, #293 caught all 54 warm-versus-empty comparisons. The integration reproduced the released reader on every comparison. The stale cases included a successful build against a malformed archive and a stale executable when a higher-priority library appeared. The table combines a direct native dependency with one reached through a Rust library. Its counts are failures against the empty-build executable or error.

| Old-writer native declarations | Comparisons per reader | Released Cargo | Experimental integration | Strict #293 |
| --- | ---: | ---: | ---: | ---: |
| Both selected archive paths | 18 | 0 | 0 | 0 |
| Both search directories | 18 | 4 | 4 | 0 |
| None | 18 | 8 | 8 | 0 |

`python3 -IB verify.py` rechecks the preserved readbacks. The records retain the actual Rust and Cargo identities, successful compiler and linker invocations, native ELF and executable-text hashes, QEMU returns, failures and provider searches. `originals.json` binds each readback to the SHA-256 of its complete original Actions archive. The original four Ruff archives include the complete program bytes. Re-run the actual source qualification with the command below. [Pinned workflow](https://github.com/astral-experiments/ohm/blob/6cb68d57fd6b5772f3c862027545bd2935e08ece/.github/workflows/ci.yml)

```sh
gh workflow run ci.yml --repo astral-experiments/ohm --ref charlie/qa-gnu-ruff-syscall -f phase=release-gnu
```
