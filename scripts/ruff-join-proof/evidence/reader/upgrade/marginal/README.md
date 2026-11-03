# The final Cargo dep-info reader on fixed Ruff inputs

This Linux experiment measures the last part of Cargo #436. P (ba07041c) and C (4a6de785) each already collect the new strong input checksums. C adds the reader and migration for ambiguous or duplicate path identities. Both used one signed d57fd151 rustc, two separate ThinLTO release Cargo binaries and physically independent writable build trees on a single boot. [Registered worker and full original](https://github.com/astral-experiments/ohm/actions/runs/41612792011)

The OLD→NEW historical Ruff RUF009 edit used ordinary `cargo +ohm check -p ruff --bin ruff --locked --offline -j4`. Both treatment orders passed the same fixed-input controls. All 1,322 declared external compiler and generated artifacts matched across the two external input trees, including the actual get_size_derive2 executable library and four locked Git packages. Every OLD and independent NEW started all 32 workspace Cargo units from empty, with all 328 external Cargo units genuinely fresh. The historical edit ran seven real rustcs. The first unchanged and independently observed JSON check ran only ty_python_semantic, while Cargo listed six non-fresh units. A private body edit ran the linter and ty_python_semantic. A real invalid type edit produced E0308 and its repair matched the independently rebuilt NEW public hashes across four crates.

| Scope | P first | C second | C first | P second |
| --- | ---: | ---: | ---: | ---: |
| OLD unchanged | 5,960,844,718 | 5,960,847,048 | 5,960,959,058 | 5,960,951,627 |
| Real edit | 26,568,771,895 | 26,564,803,001 | 26,567,331,754 | 26,568,723,017 |
| Edited unchanged | 6,418,160,271 | 6,417,965,345 | 6,417,978,217 | 6,418,080,437 |
| Private body edit | 21,468,709,008 | 21,465,097,365 | 21,464,170,013 | 21,465,912,201 |
| Private unchanged | 6,417,031,978 | 6,415,788,685 | 6,416,999,203 | 6,416,129,966 |

These are complete inherited user-mode retired instructions. All five absolute differences were under 0.02% in both orders. The signed 7024→4a6 change and fresh boots are outside this comparison, so it is a descriptive bound on this one machine. [Full-source refusal and flag-only control](../full-comparison/README.md) · [Actual migration cost](../README.md)

The matched study and a separate fully cold test had different outcomes. All four fixed-input comparisons passed their declared public-hash and compiler-roster checks. ruff_graph and ruff_workspace metadata also matched byte-for-byte between each edit and the corresponding fixed-input independent NEW. ty_python_semantic's public/private headers matched but its file bytes differed. ruff_linter's public header matched and its private header differed in both roles. The subsequent wholly empty P rebuild succeeded, but all four public headers diverged when its external inputs moved. Five generated autocfg LLVM filenames were replaced, and three common-name files changed (the get-size proc macro, its dependent rmeta and a jemalloc log). The worker stopped at its registered whole-external-name equality check. The wholly empty C step in that worker did not run.

```sh
python3 -IB reopen.py
python3 -IB reopen.py --original /absolute/path/to/original.zip
```

The compact raw data includes all physical rustc exec records and the real kernel counter files from both orders. The second command reopens every selected input from the original worker ZIP. GitHub Actions artifact 13219778236 is 138,906,749 bytes, SHA-256 `647092f0c7f37b26176cafdbe9cf204f2212a28c3d07d0fd79574e5f96b9a744`. The four fixed-input proofs run before the separate independent-cold refusal. Full standalone correctness uses the separately qualified signed and source-built compilers. [Mixed-version native tests](../../release-profile/README.md)
