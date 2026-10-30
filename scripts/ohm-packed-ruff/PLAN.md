# Packed object experiment

Run the parser build from Ruff's real #28335 with its original dependency lock
and the unmodified Linux Cargo and Wild from signed Ohm 1.99.0-20. Use one
physical source path, SDK path, target path, and shared build path across arms.
Every independent installation starts with empty target and build directories.
P and C have the same bootstrap, standard library, LLVM, Cargo, and Wild.

| Arm | Compiler | Branch histories |
| --- | --- | --- |
| Off | Candidate | Ordinary single session |
| Full | Parent b676a640 | Opt-in tables on branch switches |
| Packed | Candidate eb15cd3d | Opt-in tables and private relocatable objects |

For each installation measure a cold A, first switch to B, return to A, return
to B, and unchanged B. Then reverse the 169 tracked files from the real Ruff
change in the B working tree, with HEAD still at B. Measure the first dirty
build and the restoration. Use independent, from-empty references for each
arm, branch and working-tree variant. Compare the linked reader byte-for-byte,
its 64/56 byte layouts and a contrary Rust type check, and all named native
object bodies and link metadata in each Cargo archive. Preserve differing raw
Rust metadata. Every installation must reject an invalid Rust edit and recover.
The candidate must relink 17 to 29 after a native archive change, reject a
malformed archive, and match its clean executable after repair.

The primary performance endpoint is the entire uninstrumented Cargo build on
each return direction. Report the first switch plus return, first dirty edit
and restoration separately. Record cumulative child CPU as a secondary measure.
Count allocated blocks across target and build together, deduplicating hard
links and comparing against GNU du. Report after the first switch and each
return, as well as the observed peak during Cargo in a private mount. Preserve
object counts/allocations and raw Cargo streams.

Run two mirrored triplets Off/Full/Packed and Packed/Full/Off. Require all four
Off/Packed return ratios above two, smaller complete allocations for Packed
than Full at each of the three switch endpoints in both triplets, real packed
objects, and all semantic checks. If the screen passes, run an independent
12-triplet confirmation using all six orders twice in a fixed shuffle.
Report each individual ratio and use the third-smallest ratio in 12 as the
simultaneous one-sided lower bound for the two medians (at least 96% joint
coverage by the binomial sign distribution and union bound). Require each
bound above two and smaller complete allocation in every triplet. Native
per-rustc instruction counts in a separate acquisition cover both native Ruff
compiler invocations per return in two mirrored installations of all three
arms. Never treat an incomplete or instrumented Cargo clock as an ordinary
elapsed observation. Report those counts separately, including each crate.
