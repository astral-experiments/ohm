# Residual compiler work after Rust #329 on Ruff #29697

The ordinary library edit rebuilt unchanged-source `ty_ide` and changed-source `ty_project`. The measured six fresh hosts used a median 19.057 billion user instructions with #329. A separate kernel sample of one such build locates remaining work. That profile failed its registered 4% process-agreement gate for ty_ide (6.34%). It has no paired treatment or qualified speedup. [Six-host whole command](../../evidence-29697-six/README.md) · [Original attribution worker](https://github.com/astral-experiments/ohm/actions/runs/41664782768)

The [physical readback](ordinary-verified-native-and-holdout.json) reopened four distinct ordinary and sampled output states. In each same-source comparison, all 416 full native member names (modulo the enrolled seven-character nonce) and bodies, both symbol-to-member lookup maps and the normalized link wrappers agree. The complete rlibs and metadata bytes differ. The independent reader actually ran all four original client ELF bodies. The old pair print one pending script and the edited pair zero. Both then print one after opening it and return the same three vendored path verdicts. Clean and E0308/repair qualified on the six ordinary hosts. This worker stopped before those phases.

At period 1,000,003, the kernel recorded 19,656 samples, 141 in kernel mode. No lost, throttled or unthrottled records were observed. The complete physical image/leaf classification is in [candidate-pcs.json](candidate-pcs.json) and the per-relative-PC counts are in [candidate-pcs.ndjson.gz](candidate-pcs.ndjson.gz). On `ty_project`, 4,634 of 14,662 samples fall in LLVM. Both genuine changed-object compiler workers account for 2,550 and 1,935 samples; two other rebuilt workers whose native outputs remained identical account for 979 and 42. On `ty_ide`, 5 of 4,485 samples fall in LLVM. Its original 171 objects were all retained.

To replay from the original authenticated ZIPs on x86-64 Linux, use GNU ar, binutils, unzip, zstd, Python 3.11+, and perf. The source-built SDK, Linux shared-library build IDs, original hardware event and both actual process records are bound by the source files in this directory. Use the same captured GNU build IDs and matching libc6-dbg for full glibc symbol names. Unmatched system images remain unassigned. `read_profile.py` reads actual ELF plus mapped offsets.

```sh
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13246015936/zip > original.zip
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13225775626/zip > compiler.zip
python3 -IB ../physical.py original.zip --output native.json
python3 -IB ../prep_images.py compiler.zip images
zstd -qdc pc-readback-perf.data.zst > perf.data
perf buildid-list --with-hits -i perf.data > images/buildids.txt
python3 -IB ../read_profile.py images original.zip --output pcs.json
```

Original attribution artifact SHA-256 is `7c624a492e8f746701f650c2d1ead9c50e46865c77318f2b189c6cb8315df081`. The independently reopened kernel image bytes have SHA-256 `6afe1b1ba237948d980905a666cba2d381af545c282c96f250efb0f5d35b689b`.
