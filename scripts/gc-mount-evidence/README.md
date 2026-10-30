# Shared GC mount-boundary fixture

Run only via this one-shot hosted QA workflow. The signed Linux `-21`
package is matched to its original release asset and provenance. A
fresh private mount namespace contains task-owned paths and read/write
sentinels; every Cargo process runs as the unprivileged runner user,
with empty task-owned HOME and Cargo state. Its explicit shared-root
commands are limited to that fixture. The private-target dry run uses
a separate empty Cargo home and a tiny fixture workspace.

A native, same-device directory bind must first be identifiable by equal
source/view inode and device and different mount IDs. The real shared
GC command is allowed only if its public dry run counts precisely the
137-byte sentinel, with no skip, and leaves all relevant bytes intact.
The external sentinel is held open across the command to independently
distinguish moving the mount from actual inode unlinking. A normal ext4
file, a separate-filesystem bind, a private-target bind and a two-layer
overlay provide controls. All native Cargo arguments, outputs and
candidate unlink/rename syscalls are retained. The workflow verifies
that all mounts ended with their namespace and that the unmodified
outer mount namespace has no task mount.

The independently enrolled candidate comparison reopens a complete, verified
fork source tree in the private packaging job. A separate ext4 worker
compares signed `-21` and the compiled candidate using the same signed
rustc and normal developer settings. Each role gets separate fresh roots
and its own private mount namespace. The fixtures distinguish an eligible
legacy context awaiting retirement from an already marked trash payload.
Both have a separately eligible healthy sibling.

The candidate must preserve external inode, links, bytes and original mount
position while collecting the healthy sibling. This also applies to a
foreign-device mount. Two additional cases exercise the ordinary private
target collector and outward file and directory symlinks. A true held
profile flock must preserve the unit and releasing it must allow ordinary
productive cleanup. A regular lower-layer file in a single overlay mount
must disappear from the overlay when collected, while the original lower
file retains its bytes. No case uses a real user cache or an outer-process
mount. All subjects and every public command have separate raw receipts.
