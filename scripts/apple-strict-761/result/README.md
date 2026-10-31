# Strict Cargo repairs already-stale Apple targets

On native Apple silicon, replacing signed Ohm 1.99.0-21 Cargo with `761ea115` repaired all seven targets which had returned a stale program. With the earlier valid native archive installed, the upgraded program returned `29 7`, matching an empty build. With malformed or missing archives, the upgraded command failed with Cargo 101, matching an empty build. A declared-directory control passed on both Cargo versions. [Native workflow](https://github.com/astral-experiments/ohm/actions/runs/41151989279)

| State immediately before the Cargo swap | Placement | Signed -21 warm | Independent empty | Strict first command on the same warm target |
| --- | --- | --- | --- | --- |
| Valid higher-priority archive inserted | Direct, dependency-borne marker, dependency owning the `-bundle` archive | `17 7` | `29 7` | `29 7` |
| Previously selected archive made malformed | Direct, dependency-borne marker | `29 7` | Cargo 101 | Cargo 101 |
| All archives removed | Direct, dependency-borne marker | `29 7` | Cargo 101 | Cargo 101 |
| Higher-priority archive in a declared directory | Direct | `29 7` | `29 7` | `29 7` |

Each of the eight upgrades kept the same SDK driver inode and ctime, source, program path, target, shared directory and cached fingerprints. The packet includes a complete unchanged file inventory immediately before and after the Cargo executable swap and an independent empty build for every visit. The genuine Rust edit changed the returned program to `29 11`. Invalid source failed with E0425 on both warm and empty, and source repair returned `17 13`. Empty builds using the malformed archive and fully missing providers exercised the real linker. The registration covers 58 warm and 58 independently empty commands. [Frozen schedules and source](https://github.com/astral-experiments/ohm/tree/1112eb6e0d61a326e8d89651e015c4d86ac94c2d/scripts/apple-strict-761)

Signed `-21` rustc `c79998a5` recorded the exact unversioned `/dev/null/ohm-recheck-dependent-links` in the optimizer-barrier fixture’s compiler depfiles. All successful commands had that literal rule in their actual native files. The strict build used source tree `19c379477ec24be16c82b952dc2e892c0563e2c7`, both real Git parents, the signed compiler, `all-static,ohm-defaults` and the release dev channel. Its arm64 Cargo binary SHA-256 was `ffb32cb6a9eac1f356921b5f08c3f012b904fc3cf6b38b5696af712830a62516`. The stock Xcode 16.0 linker was `/Applications/Xcode_16.0.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/ld`, SHA-256 `2b48a59af70235283aa94c43eb0dd2ef80182c106db43279db936cc87426b443`. Endpoint Security identified the actual compiler and linker PIDs and argument vectors. [Native Cargo build](https://github.com/astral-experiments/ohm/actions/runs/41151585589)

The first migration ran three full compilers for a direct fixture or four when the barrier lived in a dependency. Both cases invoked Xcode twice, including the build script. **All 12 subsequent unchanged controls ran zero full compilers, one link-only rustc and one real Xcode link.** These are physical counts for this small developer-mode build.

Of the 58 warm/empty pairs, 39 produced equivalent correct executables, 12 returned matching errors, and seven reproduced the original signed Cargo bug. All 39 equivalent programs differed in raw Mach-O bytes. The complete comparison verified the signed code pages, the real linker’s inputs, the original saved rustc recipe and object contents, and permitted only proven invocation-specific CGU debug-name salt and its resulting CodeDirectory bytes. The packet retains all 67 distinct complete Mach-O images, both real archive contents and all original diagnostics. It contains 1,192 native entries. The original native artifact SHA-256 is `0c892309c032d080cf9103fb511ad921bf20d6abae9ad628ed44963ab7132d4b` (13,476,395 bytes).

Run the offline verifier with Python 3.11 or later from this directory.

```sh
python3 -IB reopen.py | cmp - verified.json
```
