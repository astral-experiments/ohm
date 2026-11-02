# Reconstructing Ruff objects from the compiler’s own source coordinates

The first compiler prototype produced a stale executable on a small allocation test. Its pre-optimization key ran dead-argument elimination and discarded an `allocsize` distinction that ordinary LLVM optimization later uses. Two independently emitted executables report 16 and 32. In four forward and reverse trials the compiler’s actual key compared equal and the Rust object rewriter returned the old program. Both no-attribute controls reported the expected maximum unsigned value. The first prototype was rejected. [Source, native objects and linked execution](https://github.com/astral-experiments/ohm/blob/9191b98b31043b424badbd7090354bec62b5d661/scripts/ruff-placement-allocsize/README.md)

A second prototype computes the key after ordinary LLVM optimization. Of the 21 real Ruff units, 16 had equal keys and produced complete native objects matching the edited and independent empty builds. Twelve of those 16 objects required changing bytes. Reverse reconstruction and all 42 identity checks passed. The remaining five each declined in both directions. These archived-module checks use the literal raw bitcode SHA and the full placement records from independent post-optimization parses. Reading the live compiler module and reparsing its serialized bitcode can produce different key bytes. The live check uses the same input domain on both sides. [Original Ruff build](https://github.com/astral-experiments/ohm/actions/runs/41371190920)

In the first prototype’s reconstruction of all 21 `ruff_workspace` codegen units rebuilt by Ruff #28106, the Rust helper reproduced 15 complete current objects from the previous native object and two compiler-generated placement records. Eleven required different output bytes, and four already matched. Each of the 15 matched the ordinary edited build and a separate initially empty build. Reversing the two placements reproduced the previous object. The remaining six fell back with zero output. The assertions cover all 42 identity reconstructions and all 42 forward and reverse decisions. [Original Ruff build](https://github.com/astral-experiments/ohm/actions/runs/41371190920) · [Earlier independent native comparison](../ordinal/README.md)

The compiler creates each `OSP` record from that module’s own LLVM IR. The record contains a SHA-256 commitment to canonical LLVM bitcode and compact source placements across all debug files. The Rust consumer requires an equal commitment and a compatible global ordering, checks the prior object and returns a freshly allocated ELF. It handles a restricted x86-64 GNU ELF/DWARF4 line-tables shape. The 21 prior placement records occupy 138,527 bytes alongside 14,348,624 bytes of prior native objects (0.965%). The 15 admitted prior records occupy 75,513 bytes. The design keeps a single prior native object per unit. [LLVM producer, exact wires, restoration and raw prices](https://github.com/astral-experiments/ohm/tree/52c5e15e7d03fe2314f2e64f15957a9e1999ce89/scripts/ruff-native-cgu-input)

## Instruction counts for the rejected first prototype

| Replay component | Guest instructions |
| --- | ---: |
| Original LLVM optimization and machine emission, all 21 units | 120,906,271,208 |
| Original work in the 15 admitted units | 83,908,903,279 |
| Construct current keys and placements, all 21 current modules | 7,842,462,241 |
| Read the three inputs, reconstruct or refuse, write and free the result, all 21 native calls | 342,971,495 |
| Remaining original work plus both new components | 45,182,801,665 |

The ratio of the first and last rows is 2.676× on these fixed inputs. Its premise fails on the allocation control, so it cannot justify this change to rustc. A separate archive-input parse and LLVM verification cost 3,908,761,345 guest instructions. The second prototype executes ordinary optimization before generating its key and can therefore skip only machine emission. The 16 hit modules account for 60,436,240,766 machine instructions in this corpus before the costs of both replacement stages. An ordinary Cargo measurement must also include frontend work, work-product handling and linking.

The original QA actor used identical physical placement tables but prefixed them with an experimental contextual digest instead of the raw canonical module SHA emitted by the real compiler callback. The 42 literal callback records retain all the same source decisions. Repeating the native measurements with those records added 11 guest instructions across the 21 calls. This packet preserves the earlier 342,971,484 count alongside the corrected profiles. [Original QA scope and reports](https://github.com/astral-experiments/ohm/blob/bdbedd3a3fefada3387d25792a4c4cd0d01f9170/scripts/ruff-cgu-debug-locations/evidence/41371190920/native/README.md)

The 15 successful native calls spent 342,944,776 instructions and wrote 8,499,472 output bytes. Six rejected calls spent 26,719 instructions. Valgrind 3.22.0 collected one continuous `Ir` region per new native invocation. Startup and the Python oracle were outside the region. All 21 primary samples, three preselected inverse-order repetitions by object size, and two empty markers are included. The three repetitions matched exactly. The empty regions each retired 23 guest instructions. The original 21 optimizer/emitter profiles were reopened separately and their compressed and raw digests are in `reopened.json` inside the packet.

## Falsification controls

* Two units changed a genuine non-debug input, including a source location embedded as native data. Four more retained identical machine/link meaning but failed the global line-order rule. An independently emitted two-file example changes the machine row’s DWARF `is_stmt` flag and its observable GDB step when two files stop sharing line 70. [Signed LLVM and debugger control](https://github.com/astral-experiments/ohm/blob/28f2ad253a6252632ba3a8a64dfe109a61fd99e4/scripts/ruff-cross-file-line-order/README.md)
* LLVM selects 1-, 2- or 4-byte forms for call and declaration line numbers. The six signed inline-call fixtures have identical `.text`. The previous helper really emitted a different complete ELF on 256→255 and 65,536→65,535. The current helper falls back on both directions of both boundaries. The four 254↔255 and 256↔257 controls matched independently emitted objects. The native fixture holds its test semantic commitment constant to isolate this downstream encoding choice. [Pinned LLVM integer form selection](https://github.com/rust-lang/llvm-project/blob/1b9c0d5ff9bbe7634aead059efe6b11a7eeba145/llvm/include/llvm/CodeGen/DIE.h#L176-L195)
* The saved controls include unsupported ELF sections, malformed and oversized integers, relocation changes, unknown line-bearing DWARF attributes, changed lexical scopes, columns, file identities, discriminators and semantic guards. The post-pass C++ packets omitted `core/src/intrinsics/mod.rs:438` from nine modules on each side. Every admitted object still passed its full warm, clean and reverse oracle.

## Reproduce

The compact packet contains the exact three product source files, the QA harness and lockfile, all 42 literal first-prototype callbacks, the 42 second-prototype callbacks and their independent native verdicts, the raw Callgrind reports for all 26 Rust invocations, the enrollment and the signed width fixtures. The standalone reader recalculates the result without a network connection. From this directory, run

```sh
python3 -IB verify.py
```

To repeat the full object oracle on Linux x86-64, download GitHub artifact `13109144871` from run `41371190920` as its original ZIP. The reader authenticates the entire ZIP, each of the three actual rlibs, and the 63 selected member bodies. Build with the Ohm toolchain, `cc`, `ar`, and the Valgrind development headers installed. The harness uses `gimli` 0.33.0 and `object` 0.38.1. The exported harness uses adjacent, byte-identical product sources. The two Rust variants differ in the visibility of four parsing helpers.

```sh
work=$(mktemp -d)
python3 -IB verify.py --extract-harness "$work/src" --post-o1-harness "$work/post"
CARGO_TARGET_DIR="$work/target" CARGO_BUILD_BUILD_DIR="$work/build" \
  cargo +ohm build --locked --release --jobs 1 --features qa-counter \
  --manifest-path "$work/src/Cargo.toml"
CARGO_TARGET_DIR="$work/post-target" CARGO_BUILD_BUILD_DIR="$work/post-build" \
  cargo +ohm build --locked --release --jobs 1 --features qa-counter \
  --manifest-path "$work/post/Cargo.toml"
python3 -IB verify.py --original /path/to/ordinary-13109144871.zip \
  --actor "$work/target/release/ohm-dwarf-coordinate-qa" \
  --post-o1-actor "$work/post-target/release/ohm-dwarf-coordinate-qa" --recount
```

`--actor` exercises 92 original native verdicts. `--post-o1-actor` executes 84 additional checks using the second compiler’s native records. `--recount` additionally repeats the 26 measured regions and reports both the fresh instructions and their equality with the recorded values. The stored build and engine digests distinguish the original compiler, ELF and profiler from a new local build. The option can be omitted to rerun the object checks alone.

A fresh build from the exported source reproduced all 26 original guest counts. Invoking a byte-identical copy of the original actor from a different pathname on the same worker reproduced all 176 physical verdicts and counted 342,964,310 instructions across the 21 cases (7,185 fewer, or 0.0021%). The report retains the literal counts and the actor paths for both repetitions.
