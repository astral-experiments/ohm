# Signed -21 shared Cargo GC crosses a nested bind mount

A disposable Linux worker used the official release's Cargo `2d44bd4aa`.
An eligible legacy compiler context contained an ext4 directory bind
pointing to a separate task-owned directory outside the shared cache.
The public dry run counted its one 137-byte sentinel. The real command
renamed the context into its owned trash, unlinked the sentinel through
the bind, and returned 101 when removing the mountpoint produced EBUSY.
The independent external path disappeared. An open descriptor retained
the original inode and bytes as its link count fell from one to zero.

The actual signed Cargo process (PID 4106) performed all three syscalls
in that order. It ran as UID 1001. The cache and bind reported device
66305; the outside path and bind view had mount IDs 94 and 305. The
outside sibling guard remained intact and no mount reached the outer
worker namespace. This failure occurs during explicit shared-cache GC.

The ordinary ext4 positive reclaimed exactly one file. A foreign-device
tmpfs bind was skipped. The private-target collector recognized a
same-device bind in a genuinely enrolled crate and skipped it. One
overlay, mount ID 308, reported device 52 on its directory and 54 on
its eligible regular file; the shared dry run incorrectly skipped it.
These last three controls were dry runs.

Run `python3 -IB verify.py` from this directory to re-open the exact
22,720-byte original Actions ZIP and validate all 45 members, including
the kernel syscalls, mount IDs, signed binary, diagnostics and held inode.
[Native release run](https://github.com/astral-experiments/ohm/actions/runs/41144858523)
[Original artifact](https://github.com/astral-experiments/ohm/actions/runs/41144858523/artifacts/13019729876)

The shared-device comparison entered with #157. #190 added a distinct
mount-table guard for private worktree targets. #305 does not modify
these collectors.
[Introducing shared check](https://github.com/astral-experiments/ohm-cargo/blob/a2e1b39930161b72506e0e316db1f51780a5d535/src/workspace/build_cache_gc.rs#L719-L789)
[Private mount detection](https://github.com/astral-experiments/ohm-cargo/blob/2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c/src/workspace/build_cache_gc/worktrees/mounts.rs#L9-L41)
