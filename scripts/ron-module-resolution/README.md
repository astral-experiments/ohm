# A zero-byte Ron module changes the compiler verdict after the same three span joins

The signed Linux Ohm 1.99.0-23 Ron compiler ran the same 68 calls to `Span::join`
in a successful compilation and in one that emitted E0761. Three calls in each
process observed foreign spans. All three returned the same file-relative
`Some` value. The other 65 calls and the zero foreign `Debug` observations
were counted at the native signed bridge. The only added input was a zero-byte
`src/util.rs` next to Ron's genuine `src/util/mod.rs` in a private installation.
All 555 existing files remained byte-exact. An independently empty installation
produced the same diagnostic at Ron's `lib.rs:36`. Restoring the original
tree restored the full archive and executable.

The three calls used two groups of server-global syntax contexts and one
distinct pair of operands. The imported source was bitflags' `src/public.rs`, stable file ID
`69754195d398d941cd88b96d81bd6a7d`. The operands covered bytes 549–550
and 602–610 and the return covered 549–610, all half-open. Both operands
had the same normal inline syntax context and no parent. The raw global
start shifted from 2,011,539 to 2,011,465 between the two processes. The
linked `serde_derive` ELF and the selected `serde_core` metadata mapped
the same physical files and had the same headers at all six returned calls.
The ordinary role's five explicit metadata dependencies, its proc macro and
the transitive metadata selection are in the sibling input corpus.

Six successful uninstrumented calls, including a physically earlier duplicate
or malformed unselected `serde_core`, produced the same complete rlib and
dep-info. All six linked readers produced identical executable bytes and
`valid=[8,13,21] roundtrip=3 malformed=1:5`. The native reader also had to
produce E0308 and repair. The two standalone rmeta variants were 1,442,611
bytes. Their 56 changed bytes resolved to an index permutation of two opaque
lifetimes. All 3,584 definition fingerprints, 3,240 local rows, 1,232
expansion rows and 26 dependency rows agreed.

The -24 packaging pin names Rust `f5a51d8c` and Cargo `abc70d60`. It embeds
the same span bridge, span encodings, module resolver and metadata locator as
the signed compiler used here. Its module resolver checks both filenames. The
two positive answers produce E0761. Its Cargo checks recorded compiler inputs
after prerequisites and preserves conservative treatment for a unit marked
`ohm-foreign-span-bytes`. Reopening an existing registry extraction with a
valid `.cargo-ok` record does not enumerate its contents again.

A revalidation path for a successful previous producer would need both names
from this resolution decision, a trusted generation for imported metadata
and native macro inputs, current stable expansion/parent identities and a
successful current producer boundary. A read-only manifest-backed input
namespace could establish directory membership. A mutable directory can
change while it is being checked. Records with other native effects or an
unproved input generation require ordinary compilation. This experiment
measures compiler correctness and reports no performance number.

Run `python3 -IB run.py --verify-recorded` to reopen the compact receipt.
The full replay needs a Linux x86-64 signed -23 SDK, rustup, Python 3.11 or
newer, GDB with Python, a C compiler, and libunwind development libraries.
The sibling kit is `scripts/ron-consumed-metadata` in Astral's Ohm packaging
commit `e32f0ce74548f1aff3324089cca2e363e496dbad`; its SHA256SUMS must
match the fixed digest before any new compilation. Choose a new work directory.

```sh
python3 -IB run.py --kit /path/to/scripts/ron-consumed-metadata \
  --sdk /path/to/signed-23-sdk --work /tmp/new-ron-join-run
```

The capture creates the eight ordinary visits and six native consumer
checks, then runs the signed debugger on the healthy and ambiguous cases.
The decoder reads the physical rmeta tables. The verifier reopens the
selected inputs, native results, driver observations and exact source blobs.
It emits the evidence under the chosen work directory.
