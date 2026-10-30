# A native file changed Ruff's otherwise unchanged GNU test

The ordinary `ruff_db` test on Rust #285 and Cargo #301 observed all five provider states. No Rust input changed. The forced root compilations and independently empty builds produced the same complete AArch64 ELF in every successful state and the same GNU linker error for the malformed file. The baseline and removed-provider builds restored the full 129-test inventory and passed the original round-trip test and the three regression cases under QEMU.

| Provider at `psm/…/out/libgcc_s.so` | Ordinary Cargo | QEMU | Ordinary full rustc / link-only rustc / target GNU ld |
| --- | ---: | ---: | ---: |
| Absent | 0 | 0 | 0 / 1 / 1 |
| Added before the system library | 0 | 83 | 0 / 1 / 1 |
| Replaced in place, same size and mtime | 0 | 47 | 0 / 1 / 1 |
| Malformed at the same inode, size and mtime | 101 | No executable run | 0 / 1 / 1 |
| Removed after the failure | 0 | 0 | 1 / 0 / 1 |

During the first ordinary baseline, GNU ld observed ENOENT at the private path and then opened the system's 132-byte linker script. That script separately searches for `libgcc_s.so.1` and `-lgcc`, including a failed relative lookup from the working directory. With the private provider in place, the same native linker opened the new script and its constructor object. Removal restored all 28,189,264 original bytes. These observations rule out skipping this GNU link solely from unchanged Rust objects, known library names, or a list containing only previously opened files. They do not establish that a complete GNU link receipt is available or cheap. [Registered source and commands](REGISTRATION.md) · [Full native observation](https://github.com/astral-experiments/ohm/actions/runs/41145570612)

The hosted job failed in its final Python reporting import after saving every native result. The pinned offline reader reopens all 267 files, hashes the four complete AArch64 ELFs and applies the pre-existing 17-visit acceptance function. The two earlier incomplete runs remain separate. [Offline readback](readback.json) · [Collection history](OPERATIONAL.md)

Run from this directory with Python 3 and `zstd`. The raw GitHub artifact and its SHA-256 are pinned in the reader. A previously downloaded copy works offline.

```sh
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13021026409/zip > native-41145570612.zip
python3 -IB reopen.py native-41145570612.zip
```
