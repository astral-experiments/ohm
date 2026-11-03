# Immutable native input and output bytes on the ordinary Ruff command

A diagnostic built from the exact Wild source gave the linker private immutable byte arrays from each actual opened input descriptor. It used the same arrays for native linking and its BLAKE3 record. Before returning, it checked each original descriptor and pathname generation again. A private output working buffer exposed the bytes just before Wild wrote them to its normal output. The runner independently reopened the complete canonical file and compared its BLAKE3 digest with the recorded array.

| Stage | Full native input bytes | Result |
| --- | ---: | --- |
| OLD | 618,900,091 | Signed clean OLD |
| Real edit and two unchanged builds | 618,902,647 each | Signed clean NEW, all three full native outputs identical |
| Valid earlier native archive | 618,903,733 | Full output matched NEW, while the actual library choice changed |
| Four changed symbols.o bytes and the earlier archive | 618,903,733 | Ten recorded ELF sections differed and the native constructor exited 83 |
| Malformed earlier provider | — | Cargo failed with the malformed provider's diagnostic |
| First repair after the Cargo failure | 618,902,647 | The expected Ruff test passed and the complete reference SHA check refused |

The 409 actual ordered native payloads, lengths and link modifiers on repair matched the prior unchanged run. Rustc had regenerated 139 object operand names, arguments 37–175. The expected three compiler/GCC temporary names changed as well. All recorded section payloads except the 48-byte GNU build-ID note matched. The record omits headers and padding, so the complete mismatch remains a failed gate. The diagnostic performed full native linking and retained one canonical executable. [Original donor study](https://github.com/astral-experiments/ohm/actions/runs/41702972179)

The original 39,760-byte generated object has one null symbol and 347 undefined global NOTYPE symbols. Its five sections contain a nonallocated GNU property note, the two string tables, the symbol table, and the null section. Its SHA-256 is 686f6a2749ab0d980e5627e5568850d2a8d8e79e480d6d62499241056036873d. The file content remains mandatory when generated pathnames differ. The earlier-library witness encountered 82 failed searches instead of the ordinary 94.

The donor ZIP was 2,051,118 bytes with SHA-256 35ea2b2315f26ec8866ee8d29fbe8648739a69725cf7df99441f3a4af0d60928. Reopen its physical input arrays, canonical hashes, compiler operands and rejected gate with the following commands.

    gh-auto api repos/astral-experiments/ohm/actions/artifacts/13265710693/zip > donor.zip
    python3 -IB read_donor.py donor.zip

The GNU build IDs reconstruct independently from both entire signed executables when the 48 note bytes are initially zero. The signed OLD and NEW files leave 3,751 and 3,733 bytes outside named section payloads respectively. A one-byte text change failed both the full SHA-256 and the original note descriptor on the 227,979,336-byte NEW executable. This check streamed the compressed originals without retaining another complete ELF.
