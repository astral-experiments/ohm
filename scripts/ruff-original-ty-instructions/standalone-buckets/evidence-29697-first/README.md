# First ordinary ty_ide library build pair

On one Linux boot, the complete edited library build consumed 43,425,702,707 parent instructions and 19,058,727,511 candidate instructions, a 2.2785× improvement. It retained 148 and 171 of the 171 ty_ide native objects respectively. The independently traced repeat attributed 28,525,059,754 and 4,179,893,179 instructions to ty_ide. Both compilers also rebuilt the edited dependency ty_project. [Original run](https://github.com/astral-experiments/ohm/actions/runs/41659042826)

Each SDK built 259 Cargo units from an empty target, applied the real Ruff change, rejected an invalid edit with E0308 and repaired it. A separate client linked the exact emitted libraries. The OLD client returned one script in both modes. Edited, repaired and independently empty NEW returned zero with uv disabled and one with uv enabled. All four builds passed the three vendored-path cases. Every physical client in a given source state had the same complete ELF bytes across both compilers. All 416 ordered native objects and 11,475 archive symbol lookups matched the corresponding clean result after accounting for rustc's actual generated member-name nonce. The per-definition metadata fingerprint values did vary with build history. The real edit changed the same keyed rows under each compiler. The full warm/clean distinctions are in `reopened.json`.

The first pair was excluded from the subsequent six-boot estimate. The first independent reader attempt refused to sort equivalent profile dictionaries. Serializing each complete profile deterministically fixed the reader. The same original ZIP then passed every source, counter and native check. Its initial successful readback SHA-256 was `cabb7cdb6a370d932861f8edd14010d92bdb008d9d84b1f997e385274cc6f881`. The confirmation reader adds three registration fields to the report. Its SHA-256 is `3f00626c4cfd45c67edffcf9161fc22ba287847bc650a2212ca4be200931573d`; removing just those fields reproduces every initial report value.

From this script directory, after obtaining artifact 13242330338 as `original.zip`, rerun the independent native and metadata audit on x86-64 Linux with GNU ar and zstd available.

```sh
python3 -IB reopen.py original.zip \
  --sha256 414b81d123ca59fda63aa3c15ee30410e46d8c1330529db801b0ebbc0f12e913 \
  --work /path/with/16GiB/free --output first-reopened.json
```
