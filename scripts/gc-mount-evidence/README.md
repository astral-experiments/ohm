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
