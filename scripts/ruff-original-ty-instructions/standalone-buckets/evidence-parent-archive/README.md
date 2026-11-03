# Name and native-code readback from the parent-only Ruff library build

The first 259-unit ty_ide library build passed the real project API under the parent compiler and stopped at a complete archive-member-name comparison against independently empty NEW. The candidate had not started. All 171 ty_ide and 245 ty_project native ELF bodies already agreed exactly.

Each incremental invocation draws a u32 and encodes it in fixed-width base 36. Rustc inserts this nonce between the stable codegen-unit name and the object suffix. The rlib builder keeps the real object's basename in the archive and in its late-metadata list. The nonce differs between invocations building the same source. The binding in sources.json identifies the five signed compiler source blobs. [Nonce construction](https://github.com/astral-experiments/ohm-rust/blob/d57fd1515986dccecdcece8da85e651bfb4b81f9/compiler/rustc_interface/src/util.rs#L633-L637) · [Object filename](https://github.com/astral-experiments/ohm-rust/blob/d57fd1515986dccecdcece8da85e651bfb4b81f9/compiler/rustc_session/src/config.rs#L1291-L1311) · [Late metadata creation](https://github.com/astral-experiments/ohm-rust/blob/d57fd1515986dccecdcece8da85e651bfb4b81f9/compiler/rustc_codegen_ssa/src/back/link.rs#L565-L598) · [Archive basename](https://github.com/astral-experiments/ohm-rust/blob/d57fd1515986dccecdcece8da85e651bfb4b81f9/compiler/rustc_codegen_ssa/src/back/archive.rs#L545-L550)

I reopened the original warm and clean rlibs by digest. The correspondence uses every original ordered GNU archive member, its full crate stem and stable CGU, its full native ELF SHA-256/byte length and the complete symbol-to-physical-object index. All 4,199 ty_ide symbol associations and 7,276 ty_project associations agreed. The complete rmeta-link ELF wrapper matched after normalizing precisely one observed filename per object. ty_ide invocation nonces were 18930e6 and 1u19mi4; ty_project had 17gmkq9 and 0hhjoos. The full name/body bijections are in name-bijection.json.gz.

The independently empty metadata also differed in the real enclosing compiler output. Both producer histories have exactly the same stable definitions, expansion entries and required-crate keys. There are 3,033 differing public definition fingerprints for ty_ide and 4,126 for ty_project. The ty_ide required hash for ty_project differs. All native object payloads and the edited/repaired/empty native client executables match. The full rlibs have distinct SHA-256 digests. The parent-only raw archive and program comparison cannot estimate #329 performance.

Both actual public clients were independently executed again from the original archive. The historical client selected one script with uv disabled and enabled. The edited client selected zero when disabled and the same correctly identified file when enabled. Three real ty_ide path-mapping cases also passed in each client.

The four negative cases in name_controls.py use the actual parent archive. Exchanging two distinct equal-sized native payloads preserves the original body multiset and fails the per-name verification. Redirecting one ranlib entry changes its independently decoded symbol mapping. A duplicate canonical CGU and a corrupted rmeta-link filename each stop the reader. [Original run](https://github.com/astral-experiments/ohm/actions/runs/41629561413)

From the packaging checkout:

~~~sh
v=scripts/ruff-original-ty-instructions/standalone-buckets
work=$(mktemp -d)
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13227692210/zip > "$work/original.zip"
python3 -IB "$v/name_controls.py" "$work/original.zip" --work "$work" --output "$work/negative.json"
cmp "$work/negative.json" "$v/evidence-parent-archive/negative-controls.json"
~~~
