# Reconstructing Ruff objects from the compiler’s own source coordinates

On all 21 `ruff_workspace` codegen units rebuilt by Ruff #28106, a Rust helper reproduced 15 complete current objects from the previous native object and two compiler-generated placement records. Eleven required different output bytes, and four already matched. Each of the 15 matched the ordinary edited build and a separate initially empty build. Reversing the two placements reproduced the previous object. The remaining six fell back with zero output. The assertions cover all 42 identity reconstructions and all 42 forward and reverse decisions. [Original Ruff build](https://github.com/astral-experiments/ohm/actions/runs/41371190920) · [Earlier independent native comparison](../ordinal/README.md)

The compiler creates each `OSP` record from that module’s own LLVM IR. The record contains a SHA-256 commitment to canonical LLVM bitcode and compact source placements across all debug files. The Rust consumer requires an equal commitment and a compatible global ordering, checks the prior object and returns a freshly allocated ELF. It handles a restricted x86-64 GNU ELF/DWARF4 line-tables shape. The 21 prior placement records occupy 138,527 bytes alongside 14,348,624 bytes of prior native objects (0.965%). The 15 admitted prior records occupy 75,513 bytes. The design keeps a single prior native object per unit. [LLVM producer, exact wires, restoration and raw prices](https://github.com/astral-experiments/ohm/tree/52c5e15e7d03fe2314f2e64f15957a9e1999ce89/scripts/ruff-native-cgu-input)

## Instructions on the fixed inputs

| Replay component | Guest instructions |
| --- | ---: |
| Original LLVM optimization and machine emission, all 21 units | 120,906,271,208 |
| Original work in the 15 admitted units | 83,908,903,279 |
| Construct current keys and placements, all 21 current modules | 7,842,462,241 |
| Read the three inputs, reconstruct or refuse, write and free the result, all 21 native calls | 342,971,484 |
| Remaining original work plus both new components | 45,182,801,654 |

The ratio of the first and last rows is **2.676× for the fixed LLVM replay**. Its premise is that the compiler can bypass the entire original backend for each admitted unit and use the current in-memory module for the key. The estimate includes both new components on all six fallbacks. A separate archive-input parse and LLVM verification cost 3,908,761,345 guest instructions. A complete Cargo improvement requires an ordinary source-built compiler pair and hardware counts including frontend work, work-product handling and linking.

The 15 successful native calls spent 342,944,765 instructions and wrote 8,499,472 output bytes. Six rejected calls spent 26,719 instructions. Valgrind 3.22.0 collected one continuous `Ir` region per new native invocation. Startup and the Python oracle were outside the region. All 21 primary samples, three preselected inverse-order repetitions by object size, and two empty markers are included. The three repetitions matched exactly. The empty regions each retired 23 guest instructions. The original 21 optimizer/emitter profiles were reopened separately and their compressed and raw digests are in `reopened.json` inside the packet.

## Falsification controls

* Two units changed a genuine non-debug input, including a source location embedded as native data. Four more retained identical machine/link meaning but failed the global line-order rule. An independently emitted two-file example changes the machine row’s DWARF `is_stmt` flag and its observable GDB step when two files stop sharing line 70. [Signed LLVM and debugger control](https://github.com/astral-experiments/ohm/blob/28f2ad253a6252632ba3a8a64dfe109a61fd99e4/scripts/ruff-cross-file-line-order/README.md)
* LLVM selects 1-, 2- or 4-byte forms for call and declaration line numbers. The six signed inline-call fixtures have identical `.text`. The previous helper really emitted a different complete ELF on 256→255 and 65,536→65,535. The current helper falls back on both directions of both boundaries. The four 254↔255 and 256↔257 controls matched independently emitted objects. The native fixture holds its test semantic commitment constant to isolate this downstream encoding choice. [Pinned LLVM integer form selection](https://github.com/rust-lang/llvm-project/blob/1b9c0d5ff9bbe7634aead059efe6b11a7eeba145/llvm/include/llvm/CodeGen/DIE.h#L176-L195)
* The saved controls include unsupported ELF sections, malformed and oversized integers, relocation changes, unknown line-bearing DWARF attributes, changed lexical scopes, columns, file identities, discriminators and semantic guards. The post-pass C++ packets omitted `core/src/intrinsics/mod.rs:438` from nine modules on each side. Every admitted object still passed its full warm, clean and reverse oracle.

## Reproduce

The compact packet contains the exact three product source files, the QA harness and lockfile, all 42 producer placements, the raw Callgrind reports for all 26 Rust invocations, the enrollment and the signed width fixtures. The standalone reader recalculates the result without a network connection. From this directory, run

```sh
python3 -IB verify.py
```

To repeat the full object oracle on Linux x86-64, download GitHub artifact `13109144871` from run `41371190920` as its original ZIP. The reader authenticates the entire ZIP, each of the three actual rlibs, and the 63 selected member bodies. Build with the Ohm toolchain, `cc`, `ar`, and the Valgrind development headers installed. The harness uses `gimli` 0.33.0 and `object` 0.38.1. The export changes one checkout path in the harness so it can use the adjacent, byte-identical product sources.

```sh
work=$(mktemp -d)
python3 -IB verify.py --extract-harness "$work/src"
CARGO_TARGET_DIR="$work/target" CARGO_BUILD_BUILD_DIR="$work/build" \
  cargo +ohm build --locked --release --jobs 1 --features qa-counter \
  --manifest-path "$work/src/Cargo.toml"
python3 -IB verify.py --original /path/to/ordinary-13109144871.zip \
  --actor "$work/target/release/ohm-dwarf-coordinate-qa" --recount
```

`--actor` exercises 92 native verdicts. `--recount` additionally repeats the 26 measured regions and reports both the fresh instructions and their equality with the recorded values. The stored build and engine digests distinguish the original compiler, ELF and profiler from a new local build. The option can be omitted to rerun the object checks alone.
