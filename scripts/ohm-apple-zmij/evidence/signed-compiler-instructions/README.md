# Rebuilding the same three Rust crates

After a real edit to Ruff's Python version, two independent installations of signed Ohm -20 each compiled three unchanged crates for AArch64 macOS. Callgrind selected the actual rustc processes launched by Cargo on x86-64 Linux. The complete physical compiler argument vector and all named extern inputs matched the immediately preceding uninstrumented command. Each installation produced the same complete archives before and after collection. [Measurement protocol](PLAN.md) · [Ruff source change](https://github.com/astral-sh/ruff/commit/ef23c9c39eb3029bab0139c3ea7ae6d95c4131e0)

| Crate | First install, instructions | Second install, instructions |
| --- | ---: | ---: |
| zmij | 698,076,388 | 700,117,177 |
| compact_str | 3,048,298,351 | 3,047,513,139 |
| ruff_python_ast | 3,891,278,954 | 3,895,898,154 |
| All three | 7,637,653,693 | 7,643,528,470 |

Each run observed 39 Cargo artifacts, three physical compilers and zero native linker launches. The 99 Mach-O object members and both typed parser-version checks matched the normal invocation. The numbers count every thread of the three Linux-hosted compilers and exclude Cargo itself. The results quantify work on the signed compiler. A comparison using the modified compiler and a native Darwin timing result each need separate observations.

Run the following command in this directory to check all six totals. It decodes every self-cost entry from the original profiles and reconciles each sum against the Callgrind final counter and a separate Valgrind log. The index records full physical profile and log hashes. The numeric encoding preserves all exclusive instruction costs while omitting per-machine paths.

    python3 -IB verify.py

[Native instruction totals, compiler arguments and source](counts.json) · [Self-cost record index](self-cost-index.json)
