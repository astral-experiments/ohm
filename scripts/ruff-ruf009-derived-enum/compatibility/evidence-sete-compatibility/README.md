# Consumer compatibility with the common `sete` fix

182 ordinary x86-64 Linux Cargo commands exercised the private-derive fingerprint on two source-built compilers. Both used the consumed-input writer from Rust #347 and the literal `sete` recognition from Rust #349. Parent `dad5fae340339ea631fdafc3ef27956df1ffb81a` and its direct child `e157d8912adcdae91bd43df88959f3a510bfa34a` differ only in the negotiated private-derive change.

* Three 40-command runs used real consumers that read a declared dependency’s emitted `.rmeta` in `include_bytes!`. In each, 24 kernel-observed compiler processes ran. The checksum-aware client `c1d1c6c8` detected conflicting input on the first affected check, including with the build directory under Cargo’s registry directory. The signed client supplied the default-off control.
* The 44-command same-target history switched physical compilers and clients, reopened 50 real compiler processes and independently ran the native outputs. The source registration lists each visit and expected compiler capability. Eighteen further commands exercised conflicting and agreed lexical aliases on the two compilers. Repair and independent native outputs had identical complete SHA-256 in each role.
* The first worker completed all 120 literal checks and then stopped on a receiver that still demanded the older compiler SHA. The second acquisition verified the new source hashes before the remaining 62 commands. Their original archives, including the refusal, are included here. Each acquisition alone is identified in the summary.

With Python 3.11+, Zstandard and `b3sum` available, run from this directory:

```sh
python3 -IB verify.py --b3sum "$(command -v b3sum)" --out /tmp/sete-consumer-readback.json
cmp reopened.json /tmp/sete-consumer-readback.json
```

These are correctness witnesses. The Ruff CLI native qualification and hardware pricing have separate admissions.

[Literal histories and original refusal](https://github.com/astral-experiments/ohm/actions/runs/41623623166) · [Parked and alias histories](https://github.com/astral-experiments/ohm/actions/runs/41624199212) · [Matched stage1 factory](https://github.com/astral-experiments/ohm/actions/runs/41621745224)
