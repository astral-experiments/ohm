# Signed Linux Cargo member

The first run on 98692f36a6c4c516b8baffcc2a7a2707d41a2e9d authenticated the signed distribution, checksum and release provenance. The member gate incorrectly expected a separately built Cargo binary at the same 2d44bd4a source revision. It stopped before loading a compiler or opening a Ruff installation. Its complete observation archive has SHA-256 0ec3b5b584b6f8186420311f547df35728d096492faf87237e81845b9e20115a. [Original zero-sample run](https://github.com/astral-experiments/ohm/actions/runs/41051476725)

The release tar member, its independently installed SDK and the separately installed x86 host used for the prior signed Darwin-cross study all contain Cargo abf43741c6c75f7fd4a3bcbf1db0cfc29824a07727bde4a3974b3ea44b379c1a. The second admission checks that digest and emits the observed and required member tables. The original workload, source revisions, signed archive checks and two-mirror schedule retain their original registration.

## Two separately built standard libraries

At 19fa6cd13b63b4a6f914a395c0b840b852e31ab6, the parent host compiler and native standard library built successfully. Its AArch64 standard library also built successfully. The second x.py invocation recreated the stage1 sysroot and the subsequent combined inventory detected the missing native core library. No child or Ruff installation started. Its 11 retained entries have SHA-256 3000e0c6b9b03d36af8fc878580de90b483a80cd3f270785b91dd05cd78cc4d3. [Second zero-sample run](https://github.com/astral-experiments/ohm/actions/runs/41052396739)

The successor freezes and hashes each native or target standard library directly after its original build. Both slices must describe the same Rust source and bootstrap inputs, and their entire compiler, driver and LLVM file tables must be identical. It reopens the complete combined roster for both P and C before the first Ruff installation. All compiler controls and the original two mirrors retain their registered conditions.

A separate private three-day SDK archive allows a later test-build invocation to reuse these physically verified compiler kits. The allowlist contains the compiler, native LLVM, the two standard libraries, host linker tools, and signed release Cargo and Wild. It stores the release checksum and official provenance with per-file byte digests, sizes and executable modes. The 768 MiB limit applies to this transport artifact. To restore one SDK, run the following from this QA checkout using the digest in the independent `sdk-custody.json` receipt and a new output path.

```sh
python3 -IB scripts/ohm-aarch64-linux/capsule.py linux-aarch64-sdk-pair.tar.zst "$SDK_SHA256" P "$NEW_SDK"
```

## Reopening the native probe and capsule program

At fa1c86209ccd69396ed09256c78cb2bae8b46a04, both real 117-file, two-architecture compiler kits passed their matched input gates. Their only differing file was the physical compiler driver. The parent host and AArch64 QEMU consumer produced 29, its three assembler rules matched, and its missing real assembly input failed. The child independently passed both checked-in Linux host run-make tests. The probe's final report accidentally reused its `cfg` binding for a fixture name. Separately, an isolated Python process could not import the private archive program's sibling runtime module. Neither failure admitted a Ruff command. Its 63-entry raw archive has SHA-256 12f35e766f6abf55a4979f9fee8b0fb4fc39901868cc4a309f1787973220af42. [Third zero-sample run](https://github.com/astral-experiments/ohm/actions/runs/41053510446)

The next run uses a typed target-cfg list, another name for its fixture, and an explicit sibling import under isolated Python. Across both previously returned file tables, the bootstrap installed LLVM under the driver directory and under native `rustlib`. The archive allowlist accepts both exact locations, including LLVM's short linker script. The separately reopened tables contain 115 unique objects totalling 763,421,182 bytes including the signed release tools. All benchmark and native gates retain their original definition.
