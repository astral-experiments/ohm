# Shared Cargo GC on real Linux mounts

Two independent hosted trials ran the signed Ohm `-21` Cargo and a Cargo
built from a pinned fix, with the same physical signed rustc, compiler driver
and Wild in both arms. In each trial the released Cargo unlinked a 137-byte
file outside an eligible shared cache through a same-device bind. It did
this both before retirement and from an independently prepared, owned trash
entry. Its subsequent attempt to remove the mountpoint failed with EBUSY.
Both fixed Cargo revisions preserved the outside file, its original device,
inode, content and link count, and the original mountpoint. They removed the
unrelated eligible 86-byte sibling in both cases.

| Input and command | Signed `-21` Cargo | Final fixed Cargo |
|---|---|---|
| Eligible shared context containing same-device bind | Dry run counted both files. Real Cargo removed the outside sentinel and exited 101. | Dry run counted only the sibling. The real command preserved the mount and exited 0. |
| Owned shared trash containing same-device bind | Same external unlink and error. EBUSY can interrupt cleanup of a staged sibling. | Same protection and successful sibling cleanup. |
| Shared context containing different-device tmpfs bind | Preserved external bytes but moved the foreign mount during retirement. | Preserved both external bytes and mount position. |
| File and directory symlinks into outside fixture | Removed the two links and kept their destinations. | Same. |
| Same-device bind under an enrolled private target | Kept the external file and mount in place. Removed the unrelated eligible file. | Same. |
| One overlay mount with different file and parent device IDs | Left the eligible regular file visible. | Counted and removed the 137-byte file from the mounted view. Its immutable lower file stayed intact. |
| A held shared profile lock, followed by release | Kept the file while held, then reclaimed it after release. | Same. |

Each arm ran 18 native Cargo commands, including a version check, a genuine
private-project enrollment, and dry and real GC. No host cache was enrolled.
Each arm had a separate task-owned fake external directory and an isolated
mount namespace. The GC process itself ran as the unprivileged runner user.
The retained native traces include the real Cargo `execve` and directly
attributed file syscalls. The modern Linux kernel exercised the guarded
`openat2` path. Kernels returning ENOSYS were outside this trial.

## Native Cargo library results

| Revision | Entire library on ext4 | GC tests on tmpfs | GC tests on runner overlayfs |
|---|---:|---:|---:|
| Released parent source `2d44bd4a` from the prior independent GC roster | Not enrolled in this packet | 60/60 | 46/60 |
| First candidate `2802082f` | 411/411 | 56/56 | 55/56 |
| Final candidate `c7f394c8` | 411/411 | 62/62 | 61/62 |

The final roster includes both new tests and all 60 original GC tests.
Thirteen of the 14 old overlay failures now pass. The one remaining failure,
`workspace::build_cache_gc::worktrees::idle::tests::stock_build_can_finish_opening_a_profile_after_discovery`,
is the original private-target lock test. Its real hosted libtest output
shows the assertion at `src/workspace/build_cache_gc/worktrees/idle/mod.rs:500`
on `plan.lock_profiles(...).is_none()`. The product's simulated nested-mount
regression and renamed-parent/final-symlink tests passed on all three
filesystems. The fixtures in the table above used actual kernel mounts.

The first candidate's workflow is still red. Its independent CLI observer
required signed Cargo to have deleted an unrelated staged sibling even after
the expected EBUSY. The first ext4 observer compared the literal four
libtest execution labels that end in ` - should panic` against bare listing
names, although libtest exited 0 with all 411 tests passing. The second
workflow prospectively accepted either intact complete sibling bytes or
deletion on that one signed negative. It maps the four individual
source-annotated panic labels one-to-one and records raw, logical and
complete libtest results. Its wider roster also includes the six
`build_cache_gc_roots` tests.

## Inspect or repeat

From this directory, run `python3 -IB verify.py | cmp - summary.json`. The verifier checks the source and
binary receipts, archive SHA-256 and byte lengths, cleanly finished
compilation, every selected GC command's raw output and native executable
identity, held-link counts, mount identity and all enrolled test names. The
`first` and `final` directories retain the original Actions artifacts and
their metadata. `prior-namespace.zip` is the original 34,103-byte parent
artifact. The separate first report of the signed external unlink is in the
adjacent `../result` directory.

The released Linux SDK has SHA-256
`6f550de85f95440a61b5bd1a9d2ab0528d4fcaf674fdc008f5e986d2138be6c4`.
The final fresh Cargo executable has SHA-256
`2e78b6774f1a04e6ce60ed82d3287808a09e157f433287c72f7cec1b40e598d5`.
The final native-command ZIP is 268,970 bytes, SHA-256
`a91f22a3b3155cfe9ac15635ae75fbe400f4f5b9cade55da9f8c835d02be7f8e`.
The final build and overlay/tmpfs ZIP is 89,922 bytes, SHA-256
`b063ccffd435c8ea42448dea58f927241f1ae9fd253804a14bf8bba906dd5878`.

The exact final workflow was enrolled at
`5032f93b1a2e08f3bc2f6ed6425df3f6e28bead9`. To acquire fresh native results
while the QA branch contains this source registration, use the following command.

```sh
gh-auto workflow run ci.yml -R astral-experiments/ohm \
  --ref charlie/qa-signed21-gc-mounted-storage-20261030 -f task=qualify-gc-mount
```

[Final native run](https://github.com/astral-experiments/ohm/actions/runs/41146551109) ·
[First native run](https://github.com/astral-experiments/ohm/actions/runs/41145906532) ·
[Prior parent overlay run](https://github.com/astral-experiments/ohm-cargo/actions/runs/41143876094) ·
[Final product source](https://github.com/astral-experiments/ohm-cargo/commit/c7f394c8c9aaef1272c621ff11d77dcf569ed94b)
