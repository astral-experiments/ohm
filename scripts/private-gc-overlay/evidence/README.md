# Private Cargo GC on overlay and on a reattached directory

The dated idle target held 28 removable files. Signed Linux Ohm -21 and the shared-cache GC fix both removed zero on Namespace overlay, even with every profile lock released. On ext4 they observed the actual held flock, kept the target intact, then removed all 28 after release. The private idle planner was introduced in [Cargo #190](https://github.com/astral-experiments/ohm-cargo/pull/190). The released Cargo and the shared fix still had the same private planner blob, efb251ed7eff1c948b19cdbde1bdd9306f06ed13.

| Source | Namespace overlay while held | Namespace overlay after release | Reattached original directory on ext4 |
| --- | --- | --- | --- |
| Signed -21, 2d44bd4a | 0 files, no profile flock attempt | 0 files | Removed the outside file, then returned 101 |
| Shared fix alone, c7f394c8 | 0 files, no profile flock attempt | 0 files | Covered by its unchanged private source |
| Private overlay repair alone on signed, bcac7f31 | Real flock conflict, 0 removed | 28 removed | Static preinstalled bind preserved |
| First private repair on the shared fix, 3239cc06 | Real flock conflict, 0 removed | 28 removed | Removed the outside file, then returned 101 |
| Final private fix on the shared fix, f1f1cde3 | Real flock conflict, 0 removed | 28 removed | Both resolver modes kept the outside file and returned 0 |

The signed overlay yielded 7613604 from the profile directory entry. Its lstat, fstatat and open descriptor all reported inode 1163, device 32. Its ordinary output was on device 33. Both were on mount 82. Discovery rejected the profile identity before taking the stock Cargo lock, and its files could also fail the root-device test. Under the final source, overlay PID 24417 encountered the held lock. After release PID 24463 reopened the leaf on the owning mount and unlinked the intended payload. Its held descriptor went from nlink 1 to 0. The independent sibling and target-root outputs were reclaimed, both profile lock inodes and the outside file retained.

A second test exercises an actual mount change after discovery. An independent privileged observer moves the original eligible deps directory to its own outside path and bind-mounts that same inode back into the target during the unprivileged Cargo's entry to the directory-open syscall. The device and inode remain equal. On signed -21 and the first combined patch Cargo opened the new mount, unlinked the outside payload, then returned EBUSY on the mounted directory. With final Cargo, PID 4470 received EXDEV from the real openat2. A separate process, PID 4573, ran under a seccomp filter returning ENOSYS only for openat2 and checked actual descriptor mount IDs. Both exited 0, retained the 43-byte outside file and its nlink 1, and issued zero successful unlinks for it. The kernel and fallback records both show mount 63 changing to 393. This specific scheduling test requires mount privileges for the observer. The GC processes themselves ran unprivileged. The file was moved and reattached before GC obtained its descriptor. The existing semantics for a directory renamed after its descriptor has been acquired are exercised by the separate pinned-parent unit test.

| Exact source on overlay | Previously failing named integration tests | Previously failing private lock test |
| --- | --- | --- |
| Original shared fix, c7f394c8 | 0 of 12 | Failed |
| Private overlay repair alone, bcac7f31 | 11 of 12 | Passed |
| First combined repair, 3239cc06 | 12 of 12 | Passed |
| Final combined repair, f1f1cde3 | 12 of 12 | Passed within all 63 GC library tests and in a separate invocation |

The #294-only patch retained the original shared ThinLTO refusal on a same-mount mixed-device file. The first candidate jobs additionally tried to build the integration harness with an isolated Cargo home which lacked the Cargo rustup proxy. Both failed before libtest. The original diagnostics are included. The standalone and combined suite-only reruns used the unmodified official 1.99.0 toolchain with its normal proxy. The final overlay and ext4 public commands used the same release-profile all-static, ohm-defaults Cargo built with the signed -21 SDK. Its SHA-256 is 68e6cb1b827eb622638dae66bd04e03a67e680ecfaa591dfd8501bb060edeeae. The checked-in library and integration harness used official stable 1.99.0.

The final product commit is f1f1cde375c2562e4a39d12f8835092a106a4fb8. Its sole parent is c7f394c8c9aaef1272c621ff11d77dcf569ed94b. Its tree is 1d2cfbe147b64cd4eb9d76f3bec2e7dfe7e736c5. Its source transport and complete mode/path/byte inventory are under [the registered source](../sources/final/candidate-source/spec.json). The namespace tests and the physical mount races are Linux-only. The non-Linux branches retain their existing directory-open and single-device behavior.

Run the offline verifier from this directory with Python 3.11 or newer. It consumes the eleven original evidence ZIPs directly, reopens the exact trace, process, test and outside-file assertions, and checks the archived GitHub artifact identities and digests. Its JSON must match the committed independent readback.

    sha256sum -c SHA256SUMS
    python3 -IB replay.py | cmp - independent.json

The native source and operating-system controls are reproducible from the immutable workflow revisions. [Signed and shared baseline](https://github.com/astral-experiments/ohm/actions/runs/41147017442), [first implementations and setup failure](https://github.com/astral-experiments/ohm/actions/runs/41147709004), [original named suite reruns](https://github.com/astral-experiments/ohm/actions/runs/41148107094), [signed and first combined reattachment](https://github.com/astral-experiments/ohm/actions/runs/41148393603), [final combined source and native qualification](https://github.com/astral-experiments/ohm/actions/runs/41148948376).
