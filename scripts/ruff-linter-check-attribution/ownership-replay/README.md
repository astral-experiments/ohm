# Where Ruff #27470’s 40 billion check instructions went

On the historical `Origin::path` edit, nine indirect consumers used **35,911,065,390 of 40,048,938,104 retired user instructions (89.67%)** in the ordinary `ty_server` library check. One of them, `ty_python_semantic`, accounted for 57.10% by itself. This was one Linux x86-64 run of the measured parent compiler. [Hardware run](https://github.com/astral-experiments/ohm/actions/runs/41568743506) · [Frozen registration](https://github.com/astral-experiments/ohm/tree/8d15c2cc7515d1658beb8b91467d14a1ed66829e/scripts/ruff-linter-check-attribution) · [Ruff source change](https://github.com/astral-sh/ruff/pull/27470)

| Work in the edited command | Retired instructions | Share | Ideal whole-check speedup if removed |
|---|---:|---:|---:|
| Producer `annotate_snippets` | 1,153,688,119 | 2.88% | 1.030× |
| Two direct consumers | 2,461,909,223 | 6.15% | 1.065× |
| Nine indirect consumers | 35,911,065,390 | 89.67% | 9.679× |
| Cargo, rustup and work outside the 12 physical rustc subtrees | 522,275,372 | 1.30% | — |
| Whole Cargo process tree | **40,048,938,104** | **100%** | — |

| Physical metadata-only rustc | Relationship to producer | Retired instructions | Share | Ideal individual speedup |
|---|---|---:|---:|---:|
| `ty_python_semantic` | Indirect | 22,866,380,349 | 57.10% | 2.331× |
| `ty_python_core` | Indirect | 3,264,808,620 | 8.15% | 1.089× |
| `ty_project` | Indirect | 2,806,553,365 | 7.01% | 1.075× |
| `ty_server` | Indirect | 2,497,216,173 | 6.24% | 1.067× |
| `ty_ide` | Indirect | 2,495,952,798 | 6.23% | 1.066× |
| `ruff_db` | Direct | 1,924,726,975 | 4.81% | 1.050× |
| `ty_module_resolver` | Indirect | 1,565,715,926 | 3.91% | 1.041× |
| `annotate_snippets` | Producer | 1,153,688,119 | 2.88% | 1.030× |
| `ty_site_packages` | Direct | 537,182,248 | 1.34% | 1.014× |
| `ruff_ranged_value` | Indirect | 161,375,864 | 0.40% | 1.004× |
| `ty_vendored` | Indirect | 142,929,009 | 0.36% | 1.004× |
| `ty_combine` | Indirect | 110,133,286 | 0.27% | 1.003× |

For any subset, the bound is `whole / (whole − sum of selected rustc counts)`. It assumes every selected invocation can be removed for free while other work stays fixed. For example, the four commands for `ty_python_semantic`, `ty_project`, `ty_ide` and `ty_server` together cost 30,666,102,685 instructions (76.57%, 4.268× upper bound). The ability to skip any one of them requires a separate correctness demonstration. This run measured instruction ownership. A performance claim would require a correct implementation and a separate matched comparison.

## Physical and native controls

* Ruff changed from `c6c4d38bbeeae91fe59d9c277a78169db8306561` to `97065696c0e4dbe6ff43a89c73f923bf60ee231a`. The original SDK receiver reopened the parent built from `259ad7069e47eaf08cf106f187b2b6393f7fd7c2`, rustc frontend `8bfdc977…`, driver `0d49e63d…` and Cargo `3ce4e300…`. The two preceding real parent edits used 39,977,383,841 and 39,981,757,043 complete instructions. They recorded one hardware counter per command. [Matched compiler factory](https://github.com/astral-experiments/ohm/actions/runs/41562405539) · [Prior two histories](https://github.com/astral-experiments/ohm/actions/runs/41564417950)
* Ordinary `cargo +ohm check -p ty_server --lib --locked --offline --message-format=json` retained eight Cargo jobs, original physical target and shared paths, and a 279-unit typed roster. Old and empty-new each executed 283 compilers. The only per-boot normalization in those cold count inventories was the random 16-hex autocfg crate name, preserving the two probe families and all three suffixes. The quoted edit matched each of the 12 original rustc argument arrays after normalizing its SDK shard in path-valued arguments. Full original arguments remain in the ledger.
* The edited tree contained 14 actual execs and 71 process/thread lifetimes. Each of the 12 separately counted rustcs matched a distinct dirty Cargo artifact and produced metadata. Both direct consumers had the actual producer `--extern`; all nine others took `--extern ruff_db`. Cargo's independent unit graph confirms each path. All successful metadata checks, warm and clean, had the same empty diagnostics. The immediate unchanged run took 412,372,919 instructions with zero compiler or linker actions.
* A source-matched type error produced Cargo 101 and the expected E0308 from `annotate_snippets`. Repair ran all 12 compilers successfully. All 31 edited metadata files matched the unchanged and repaired outputs byte-for-byte. Seven of 31 matched independent empty-new bytes. The same 24 differed on both earlier ordinary parent histories. The decoder reopened the 12 original witness bodies (four crates each at old, edited and clean). The stable definitions and their exact aggregate hash-change counts reproduced both earlier parent histories. In the edited-versus-clean comparison, the producer had zero changed reachable definition hashes. The full bytes and the public hashes of the three downstream witnesses differed, just as in the two prior controls. Whole-target warm and clean metadata therefore remained distinguishable. [Per-definition and native checks](evidence/verified.json)
* The original user-space PMU was calibrated using 28 known native loop, child, exec and pthread probes and eight nested process-tree controls. The event descriptor opened for each compile at the kernel stop on its actual SDK executable, before its code ran. Children were disjoint, every owner exited successfully, and every event's enabled time equaled its running time. The Cargo denominator already includes every child. The verifier rejected six altered ledgers, including overlapping owners and a missing or multiplexed sample. [Raw member hashes](evidence/custody.json) · [Negative controls](evidence/verifier-controls.txt)
* A prior workflow attempt rejected the inherited two-worker matrix identity before SDK acquisition or any Cargo or hardware observation. The corrected preregistration binds exactly one hosted worker. [Refused attempt](https://github.com/astral-experiments/ohm/actions/runs/41568307354)

## Reopen the measurements

From this directory, with Python 3.11 or later and zstd:

```sh
python3 -IB reopen.py evidence/native.zip \
  0c205b6d0c8731047f2b27d7629922e2ef16abe575f13eef9b1438700a9c7495 \
  compiler-schema.json /tmp/ruff-27470-instructions.json
cmp /tmp/ruff-27470-instructions.json evidence/verified.json
python3 -IB mutations.py evidence/native.zip
```

The original Actions ZIP was 5,317,941 bytes, artifact `13199434825`, SHA-256 `c550dc007a27d43fc4627efd3bb85001b5c5f1ea922bbd6a97a29a9a1a259650`. The durable packet contains 226 original members in deterministic ZIP framing. The independent reader reproduced all owner totals, whole counters, 279-unit graphs, original native error/repair outcomes and definition changes from both ZIPs. Pass the compiler source checkout in place of `compiler-schema.json` to derive the symbol and metadata tables from the two verified source files instead. [Rust source](https://github.com/astral-experiments/ohm-rust/tree/259ad7069e47eaf08cf106f187b2b6393f7fd7c2)

To re-enroll the physical acquisition on the dedicated packaging QA branch after reviewing its current head:

```sh
ref=charlie/qa-ruff-27470-crate-instructions-20261103
sha=$(git ls-remote https://github.com/astral-experiments/ohm.git "refs/heads/$ref" | cut -f1)
gh workflow run ci.yml --repo astral-experiments/ohm --ref "$ref" -f reviewed_head="$sha"
```
