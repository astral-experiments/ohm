# Why independently built get-size macros print different first errors

The unscored historical RUF009 pilot used get-size-derive2 0.5.1, attribute-derive 0.10.3 and attribute-derive-macro 0.10.3. The identical original Ruff lockfile binds all three registry archives included here. The primary Cargo edit, both independent clean histories, native verdicts and two raw hardware counts remain in the original refusal. [Original record](https://github.com/astral-experiments/ohm/blob/35f44d892a88b90b30941a26bdef562e874b920d/scripts/ruff-ruf009-derived-enum/evidence-empty-pilot-41627091024/README.md)

In get-size-derive2's src/lib.rs, StructFieldAttribute declares all three pairwise conflicts among size, size_fn and ignore. In attribute-derive-macro's src/lib.rs, Conflicts::insert sorts each two-name pair and inserts it in a standard HashSet. Conflicts::to_tokens iterates the set directly and generates an early-return check for each pair. Compiling the proc macro therefore fixes the sequence of conflict checks in that particular binary. Its subsequent expansions retain that order.

Five real, independently built 3,204,376-byte macro bodies produced all three possible first diagnostics for the three-way input. Every changed byte of .text relative to the first body is within StructFieldAttribute's FromPartial::from. The four other images differ there by 153, 1,299, 1,282 and 1,236 bytes, respectively. The saved section inventories include the data, unwind, Rust metadata and build-ID differences. Each of the three separate two-option inputs in the original Rust probe produced its unique conflict at the same line. The valid expansion also matched in all 22 recorded observations. Those observations include repeated uses of the same physical image. [Native section comparison](elf-variants.json) · [Original diagnostics and image identities](reopened.json)

Both historical Ruff trees contain just three literal get_size helper attributes in the searched tracked Rust sources. Each specifies one option. That observation is limited to authored literal attributes. A run of the original capsule also independently produced the native CLI verdicts. [Source readback](locked-sources.json) · [Native reference](https://github.com/astral-experiments/ohm/blob/d89d98c6417536da40b875ed72463187a1f602e5/scripts/ruff-ruf009-derived-enum/evidence-empty-native-41625608181/README.md)

The independently empty CHECK histories also had different physical get_size2 metadata, 15 changed upstream crate hashes, and 28,297 of 38,075 different logical linter fingerprints on the parent, 28,431 on the candidate. Choosing a single unambiguous negative in a subsequent study would resolve the diagnostic comparison alone. The original native inputs and metadata gates must still be qualified. The received pilot contributed zero pairs; no confirmation workers were started.

To reproduce, use a Ruff Git repository containing 710c60f7135879b05f6c05a34085cd7af5c19e7f and b00f68a23cedbd3a38fc25bac63638f0f11fc3f0. Run the following in this directory with Python 3.11+, Git, zstd, and GNU c++filt. It reopens the exact registry packages, five complete ELF images and recorded outcomes. It runs no compiler.

```sh
sha256sum -c SHA256SUMS
python3 -IB verify.py /path/to/ruff > /tmp/ruff-locked-macro-reopened.json
cmp reopened.json /tmp/ruff-locked-macro-reopened.json
```
