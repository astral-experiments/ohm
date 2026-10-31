# Ruff diagnostics and Linux mount boundaries on one Cargo executable

Cargo `70573e256d0d7e8ca0eac763e80f93b5bd79cdc4` combines Rust diagnostic recovery in Cargo #305 and shared GC protection in Cargo #306. The source tree matches the clean Git merge of the two PR heads. All 3,109 tracked files were verified by mode, path and content before the release-style build. Both investigations used the exact same Cargo binary, SHA-256 `39ed11556c08de95863961763f9d95e3c61994193dbb756e6667beb3279bffe2`, with signed `-21` rustc. [Combined Cargo source](https://github.com/astral-experiments/ohm-cargo/commit/70573e256d0d7e8ca0eac763e80f93b5bd79cdc4)

On Ruff, signed Cargo and a release-channel-matched rebuild of its source both replayed a stale E0308 after the source had been repaired. Installing the combined Cargo at the same path restored the real deprecation warning. Its first check ran 304 rustc processes and 48 native links, matching the independent empty build. The next check ran `ron` alone and zero linkers. Both swaps with Ohm defaults disabled reused the healthy cache without running rustc or the linker. Reopening each compiler diagnostic and process record verifies 19 genuine `cargo check` visits. [Build, checks and GC](https://github.com/astral-experiments/ohm/actions/runs/41147281908)

We also paused the unprivileged collector at the instant it opened a marked trash entry’s owner file. The mount had been absent when GC inspected the directory. While the collector was blocked on a kernel permission event, a separate process in the same private mount namespace attached the test-owned external directory to its payload. Signed Cargo unlinked the external sentinel and exited 101. The combined Cargo exited successfully, kept its original inode and link count, and reclaimed an unrelated file. A second run forced `openat2` to return `ENOSYS` and verified the fallback read mount IDs from `/proc/self/fdinfo` and preserved the same properties. Both exercised the current Linux kernel. [Late-mount run](https://github.com/astral-experiments/ohm/actions/runs/41148005516)

Private-target GC uses a separate directory-opening path. Moving an already discovered private directory outside the target and binding it back exposed a second external unlink on signed Cargo and an initial private-target patch. [Private-target reproduction](https://github.com/astral-experiments/ohm/actions/runs/41148393603)

The four ZIP files are the original GitHub artifacts from those runs. The offline verifier checks their hashes, native process arguments and identities, compiler messages, filesystem state and unlink syscalls. Run from this directory on a checkout of this revision.

```sh
python3 -IB verify.py | cmp - summary.json
```
