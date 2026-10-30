# Ruff's repeated AArch64 build

After Ruff's Python 3.15 edit, the parent compiler rebuilt `zmij` on each unchanged Apple Silicon build. Recognizing its vector-register assembly comment let Cargo reuse the existing artifacts. Across twelve confirmation pairs, the first repeat fell from 157.2 ms to 41.6 ms. The median paired speedup was 3.82×, with a 96.14% interval of 3.58–4.00×. [Native measurements and offline verifier](native-apple-result-v1) · [Ohm Rust #276](https://github.com/astral-experiments/ohm-rust/pull/276)

The signed `-20` Apple baseline records which compiler actually ran on two unchanged visits. The separate Linux measurements count instructions executed by the three rustcs that the signed Linux toolchain launched while targeting macOS. The native Apple comparison above measures the tested patch. [Signed macOS process records](native-signed-baseline) · [Signed Linux cross-compiler instruction counts](signed-compiler-instructions)

From this directory, reproduce the native comparison with the Python standard library.

```sh
python3 -IB native-apple-result-v1/verify.py
```
