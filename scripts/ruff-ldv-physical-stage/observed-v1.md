The original factory at d92af19f3e0e9b043a2214f154872a70f20b4e5f stopped before
source construction on [run 41424485542](https://github.com/astral-experiments/ohm/actions/runs/41424485542).
The toy inferior loaded both named libraries and exited before the original
reader observed both matching /proc/maps devices and inodes. That record
does not identify the cause of the mismatch. The replacement rereads the real
loader mmap file descriptors, compares their complete SHA and fstat identities,
checks returned executable mappings and live instruction bytes, and reads the
live GNU build IDs at their registered ELF note offsets. The source bundle,
factory, six-pair schedule and outcomes are unchanged. The GNU ELF note reader
is shared with the independently tested 3f7cdcd5 upstream mono-owner probe.
