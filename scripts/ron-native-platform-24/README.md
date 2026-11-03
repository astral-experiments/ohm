# What the ordinary Linux -24 Ron process can establish

In two independently emptied Ruff #29697 workspaces, the unchanged published Linux -24 command `cargo +ohm test --no-run --locked --offline -j4 --message-format=json` produced 623 Cargo artifact rows, 50 real link-only rustcs and 50 real Wild links. Three full rustcs ran. Complete hardware counters give the following upper bound for removing Ron on this exact command.

| Independently seeded boot | Whole empty command | Whole unchanged command | Unchanged full Ron rustc | Largest whole-command improvement if Ron were free |
| --- | ---: | ---: | ---: | ---: |
| PC | 6,275,286,266,654 | 124,093,004,237 | 9,325,493,253 | 1.08126× |
| CP | 6,275,371,995,801 | 124,097,892,258 | 9,329,576,561 | 1.08129× |

The other two full compilers were insta and insta_cmd. The reader recomputes the individual counts from real per-thread hardware rows, the original physical `execve` argument packets, and the independent inherited whole-command counter.

## Linux file identity

The ordinary hosted container exposed an overlay identity at the open file and a different device at the executable mapping. On both fresh workers the signed frontend, driver and LLVM had identical inode numbers across those interfaces, but freshly opened regular files identified device 0:33 and the loaded segments identified 0:32. The selector refused, the ordinary compiler succeeded, and the controlled treatment supplied zero observations. A separate full-closure reader also refused before pricing. [Signed whole-workspace refusals](../ron-ordinary-backend/refused-private-overlay-6dfb8fb.json)

A small independently booted native program produced the same value 17 from identical named files on separate private tmpfs generations. All three actual executable addresses (main, the dynamically loaded helper and libc) then matched the held descriptors’ device and inode, each lease held, and Linux blocked a real conflicting writer. The original hosted result remains a refusal. [Native topology program and receiver](../ron-ordinary-backend/runtime-hardware/topology.py)

On a real block-backed ext4 installation, two independently empty ordinary builds with the unmodified published -24 SDK produced and ran the same executable. All twelve executable files in both compiler processes matched the named devices and inodes through statx. The intervening settled Cargo command emitted a fresh artifact with zero physical owner compilers. Nine mandatory system files had a different UID from the compiler, zero effective process capabilities, no measured fs-verity digest and no supported file seals. Their backing ext4 superblock was writable. We did not request leases on any shared installation file. One example differed across the two environments despite a matching name and size. Both versions of libz.so.1.3 were 113,000 bytes, with SHA-256 f61677c7… on ext4 versus 86200da3… in the hosted runner.

Those nine files prevent the demonstrated all-input policy from applying by default on this genuine installation. A separate experiment charges creating the private runtime, its allocated bytes, and repeated whole-compiler checks. The 2.15× three-file guest result has its own data and scope. [Earlier compiler measurements](../ron-existing-rlib-evidence/README.md)

## Recheck

From a checkout containing the adjacent evidence directories, run the following commands. The offline verifier includes the native topology archive, two original per-thread kernel traces, six normal or refused signed histories, local ext4 kernel observations, the working native executable and negative tests for an altered real counter and an altered inode. `origins.json` binds each subcorpus to its original native archive.

```sh
sha256sum -c scripts/ron-native-platform-24/SHA256SUMS
python3 -IB scripts/ron-native-platform-24/verify.py
```

To run the small non-root ext4 check on another Linux x86-64 host, supply an independently downloaded signed Linux -24 SDK and its real private rustup toolchain link. The receiver reopens all 79 signed files before invoking normal Cargo, keeps the generated target and build directories separate, and records the actual local access policy and outputs.

```sh
python3 -IB scripts/ron-native-platform-24/sample.py \
    --sdk /absolute/path/to/ohm-24-sdk \
    --rustup-home /absolute/path/to/rustup-with-ohm-link \
    --work /absolute/new/private-ext4-study
```
