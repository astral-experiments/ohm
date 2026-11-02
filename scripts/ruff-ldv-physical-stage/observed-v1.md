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

[Run 41425541148](https://github.com/astral-experiments/ohm/actions/runs/41425541148)
then built both original source trees, passed all factory Cargo controls and
uploaded the 185,555,780-byte authenticated SDK artifact 13131394450. The
off-clock reader separately refused the real signed LLVM ELF: it has no GNU
build ID. Its 40-byte GNU linker script is a distinct link-time file. The
next observation consumes that frozen artifact, verifies an optional GNU
build ID where present, and hashes every byte in every actual executable
PT_LOAD directly from the live mapped library. On the original signed LLVM,
this covers 69,720,216 and 37,320,372 executable bytes. The complete mmap
FD bytes and the precise first instructions at each breakpoint are also
bound. Every other admission and the source experiment is unchanged.

The next readers preserved two pre-installation failures (a missing workflow
in sparse checkout and a runner without GDB). Run 41428062362 authenticated
the complete preexisting capsule, then stopped the real P compiler on its
ordinary SIGUSR1 before exit. The observer now delivers SIGUSR1 to the
inferior without interrupting it. A sacrificial program must receive exactly
one genuine wakeup and terminate successfully; all other stop handling and
every live executable-byte check remain in force.
