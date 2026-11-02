# Trait-impl predicates after uv #21041

On the generated-impl prototype, 49 previously identified type-checking and borrow-checking calls still ran after this edit. Native tracing found the first rejected dependency for every one. Four immediate trait-solver queries all lead to the predicates of the same external `Archive` impl.

The bound is `Box<[HashDigest], Global>: rkyv::Archive` before the edit, after it and on an independent clean build. The recorded span moves 677 bytes, from line 736 to line 776. Ten of the 49 calls also read another positively changed input. The other 39 previously consumed 424.12M and 423.42M guest instructions in two runs. Those figures describe earlier work whose reuse still needs measurement. [Native trace and qualifications](first-veto.md) · [Four immediate readers](native-readers.json)

The reduced two-crate case exercises trait application, associated-type normalization and the real foreign bound in a compiler diagnostic. I registered the performance and correctness criteria after tracing the old compiler, before compiling the change. The first comparison uses two opposite-order paired openings of the real edit. A release claim requires eight new balanced pairs. [Study plan](protocol.json) · [Reduced fixture](reduced-fixture.json)

To replay the 49 original paths and the known competing inputs, extract `first-veto.tar.xz` into an empty directory and run `sha256sum -c SHA256SUMS` and `python3 -ISB replay.py` there.
