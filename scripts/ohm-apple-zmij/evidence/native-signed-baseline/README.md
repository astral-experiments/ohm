# Signed native Apple Silicon baseline

After the Ruff edit, both unchanged invocations of Cargo reported three dirty crates. Kernel events captured the physical macOS executable path, process ID, code-signing hash and complete argument vector. Each unchanged invocation executed one rustc for zmij. The other two dirty units, compact_str and ruff_python_ast, launched no compiler. Neither invocation called the native linker. The same observer saw 39 full compilers and eight Apple linker processes in the cold build. [Signed native qualification](https://github.com/astral-experiments/ohm/actions/runs/41041752760) · [Ruff edit](https://github.com/astral-sh/ruff/commit/ef23c9c39eb3029bab0139c3ea7ae6d95c4131e0)

The runner built an independent reader, executed both Python-version accessors, rejected an inserted undefined name, then accepted the repair. Replacing a real native archive changed its consumer from 17 to 29. Removing or corrupting the archive failed the build as expected. The repaired executable matched an independent clean build. The Apple time tool attributed user CPU to all three calibrated process depths. It exposed no retired-instruction value at any depth. This was an unscored baseline.

From this directory, run the following command to compare each original Cargo JSON stream with its matching kernel events. The files were copied verbatim from the verified workflow artifact.

    python3 -IB verify.py

The original archive contained 169 files and occupied 675,702 bytes. Its SHA-256 is 59ddb34bec295f0b9f61b934a94839fc8430c8dd7325dc7b5c5e2cef1de32839. [Native source and enrolled checks](https://github.com/astral-experiments/ohm/tree/60d2be35381f833d0a27b9b340922c19c8ef222e/scripts/ohm-apple-zmij) · [Registration, compiler identity and original control results](study.json)
