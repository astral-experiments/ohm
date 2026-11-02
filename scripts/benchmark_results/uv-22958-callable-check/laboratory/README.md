# Rustc instruction counts after uv #22958

The full callable-receiver change cut instructions in the unchanged `uv_client` rustc by **27.36%** and the sum of both dirty rustcs by **22.72%**. Both met the registered 20% threshold in all six pairs. Each pair applied the full landed edit to an independently checked A tree in each compiler's natural cache. Signed Ohm −22 Cargo ran `cargo check -p uv-client --locked --offline -j8` with the original 543-unit graph. The study compares stage1 `26210096` with `f2282534`, including `26ae4bbc`. [uv edit](https://github.com/astral-sh/uv/pull/22958) · [Callable-receiver compiler change](https://github.com/astral-experiments/ohm-rust/pull/327)

| Endpoint | Mature median | Callable median | Paired median cut |
|---|---:|---:|---:|
| `uv_client` rustc | 4.856B | 3.528B | 27.36% |
| `uv_configuration` rustc | 2.408B | 2.086B | 13.36% |
| Both rustcs | 7.265B | 5.614B | 22.72% |
| Cargo and descendants | 8.113B | 6.463B | 20.34% |
| Ordinary package wall | 1.116 s | 0.865 s | 22.47% |

All twelve independently seeded native histories passed before the first measured visit. The ordinary wall measurement used its original timeout wait, which could observe process exit up to about 50 ms late. Cargo's own rounded completion messages bound its median candidate/control ratio between 0.7570 and 0.7736. The two hardware counts and ordinary elapsed time were collected in separately restored visits. [Original private service artifact](https://github.com/astral-experiments/ohm/actions/runs/41411252543/artifacts/13125698743)

Run `python3 -ISB verify.py` after extracting this packet. Python 3.11 or newer suffices. The reader reopens the 196 byte-preserving original input members used to recompute the five paired endpoints, both clock summaries, machine origin, native manifests and calibration checks. To compare every included member against the service ZIP, run `python3 -ISB verify.py --original /path/to/original.zip`. The complete service artifact has SHA-256 `33846becce13a3c0f552669b0d8243be0a90c64a20152eabc61f34ec2f04975a` and also includes all 1,125 content-addressed product blobs and 80 product inventories. The original exact-cold-byte study remains refused. The separate diagnostic used preregistered controls for physical metadata variants and retained the earlier hosted attempt's refusal. [First hosted attempt](https://github.com/astral-experiments/ohm/actions/runs/41407544748)
