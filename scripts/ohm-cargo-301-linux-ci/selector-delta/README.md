# Linux-host qualification of Cargo #302

On an x86-64 Linux host, switching between Cargo #301 and #302 moved only the built-in `aarch64-apple-darwin` library between the v2 and v3 fingerprints. That target compiled once after either switch and was fresh on each next build. The unflagged Linux host, explicit x86-64 Linux, AArch64 GNU Linux and an absolute custom JSON also named `aarch64-apple-darwin.json` were fresh across both switches.

| Phase | Built-in Apple | Each other target |
| --- | ---: | ---: |
| Cold #301 | 1 | 1 |
| Repeat #301 | 0 | 0 |
| Upgrade to #302 | 1 | 0 |
| Repeat #302 | 0 | 0 |
| Downgrade to #301 | 1 | 0 |
| Repeat #301 | 0 | 0 |
| Independent empty #302 | 1 | 1 |

Counts are genuine rustc crate compilations. Each of the 35 invocations used ordinary `cargo +ohm build --locked --offline --lib` with the same signed Ohm -20 rustc. The JSON target also used the unstable JSON-target switches. The dependency-free fixture exports a function returning 17. The verifier opens the actual typed Cargo output, kernel exec stream, recorded fingerprint, the complete archive and its target object. It verifies the compiled constant, the ARM64 Mach-O or Linux ELF machine, the metadata, and the complete object bytes for each target. Each Apple archive is byte-identical across all seven commands. An independent GNU/Linux empty build may choose a fresh seven-character codegen member name. The verifier checks that replacing its two occurrences reproduces the entire archive and separately compares its emitted object and metadata. No system linker ran in these library commands. The two official native macOS jobs cover Apple execution separately. This focused qualification adds no full Linux suite for #302.

## Reopen

With Python 3 and GNU `ar` on Linux, from this directory:

```sh
sha256sum --check SHA256SUMS
records=$(mktemp -d)
tar -xzf selector-records.tar.gz -C "$records"
python3 -IB verify.py "$records" matched | cmp - verified.json
```

The source and binary construction used exact #301 `c18e91b514b2c4e4966c9ab03232c804af3e1b57` and #302 `9a102b4519b40f9034aa40533d92c83583dcb289`. Both Linux Cargos were compiled in independently empty targets at the same logical path with identical toolchain, Cargo.lock and features. Each package matched its own Git version stamp and all 3,114 source entries. The preliminary shared-target constructor reproduced its parent version stamp in both images and was excluded. An independent control used identical #301 executable bytes across all 35 commands and observed no upgrade or downgrade compiles on any target. [Matched private construction](https://github.com/astral-experiments/ohm/actions/runs/41116434431) · [Excluded private construction](https://github.com/astral-experiments/ohm/actions/runs/41116110741)

The original observed-result commitment is in `original-result.json`. `selector-records.tar.gz` preserves all 35 kernel streams with private path prefixes replaced, the Cargo output, fingerprint values and unmodified native artifact bytes. The compact result differs only in the hash covering original paths in the kernel streams.
