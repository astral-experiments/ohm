# Reproducing both archived native generations

The first local registry-input trial saved only SHA-256 for a surprising repaired executable. On the original project and installation paths, fully independent ordinary Cargo builds subsequently produced both complete x86-64 Linux ELFs. With one Cargo job the repaired executable was `ef3666e9492eb061214900eee8b45a2d3e7c8756ff9f75e0102f889b6fa42c01`. With two jobs it was `b313651b8681f33704132fa43ad3fd20088135fd51c0d53eb25f3f4dabf4190a`. Each matched its own independently empty build, including the complete debug sections and native output.

Exactly 33 bytes differed. Bytes 896–927 held the GNU build ID, and byte 7,277,000 held the low byte of the non-loaded `.rodata` section header's `sh_entsize` (0 or 1). The reader reopens all 41 section headers and four loadable segments. Changing the section-header byte, zeroing the entire build-ID note, and recomputing Wild's actual BLAKE3 build ID reconstructs the other complete executable. This held for the original and the genuine changed behavior. Both job widths rejected the malformed input twice with E0308. The registry source retained the same device, inode, length and nanosecond mtime throughout.

A separate direct linker check used one archived 42,388,800-byte operand set. One versus two Wild threads reproduced the same 33-byte difference on those inputs. Four and eight threads agreed with two. All eleven invocations ran the expected native program. The archived-link pair has different complete hashes from the original Cargo pair. The receipt keeps their identities and the complete operand hashes separate.

Run the following from this directory with Python and a C compiler. The verifier reopens the six retained whole binaries, independently parses their ELF headers and native diagnostics, and compiles the included portable BLAKE3 implementation to verify all six IDs.

```sh
python3 -IB reopen.py > /tmp/ohm-same-stamp-elf.json
cmp /tmp/ohm-same-stamp-elf.json verified.json
```

This accounts for the initially lost generation using its original SHA-256. The measured Cargo fix has its own independent complete ELF and timing controls. Wild has since fixed grouping-dependent `sh_entsize` upstream. [Wild #2816](https://github.com/wild-linker/wild/pull/2816).
