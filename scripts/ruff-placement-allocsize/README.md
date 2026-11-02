# An allocation-size change defeated the experimental codegen key

The experimental compiler revision returned the same key for two valid LLVM
modules whose clean executables returned **16 and 32**. Its Rust object
projector then accepted the old object in both directions. This invalidates
the broad dead-argument normalization used in the initial Ruff projection.
The affected code was present on an experimental branch. [Frozen compiler](https://github.com/astral-experiments/ohm-rust/commit/d5541719a447bbf9c853981296b182265ebf79d3)

The allocator always reserves 64 bytes. Its LLVM `allocsize(0)` attribute
lets the caller observe the requested size with `llvm.objectsize`. The
ordinary O1 pipeline folded that observation into the constant 16 or 32.
The experimental key ran dead-argument elimination first, which removed
the apparent unused argument along with its allocation-size attribute.
Both inputs then produced SHA-256 `6242aafd2f73cea9eab820a267ee34c6224ab8c97274cdecaaf134756515d3fa`.
The independently linked clean objects differ in the immediate moved into
`%eax`. [LLVM source](https://github.com/rust-lang/llvm-project/blob/1b9c0d5ff9bbe7634aead059efe6b11a7eeba145/llvm/lib/Transforms/IPO/DeadArgumentElimination.cpp#L842-L844)

| Allocation-size attribute | Edit | Projected executable | Clean executable |
| --- | --- | ---: | ---: |
| Definition and call | 16 → 32 | 16 | 32 |
| Definition and call | 32 → 16 | 32 | 16 |
| Definition only | 16 → 32 | 16 | 32 |
| Definition only | 32 → 16 | 32 | 16 |
| Absent | Either direction | `UINT64_MAX` | `UINT64_MAX` |

`objects.tar.gz` contains the six LLVM inputs, six complete compiler records,
six independently emitted clean objects and six objects the actual Rust
projector returned. The ~2.4 KiB compressed archive also preserves the two
successful controls. To relink and execute every direction on x86-64 GNU/Linux,
run the following from this directory.

```sh
python3 -IB verify.py
```

To reproduce the compiler and projector steps as well, build the wrapper from
the frozen compiler with the signed LLVM 23 headers and shared library, then
use the ordinary O1 emitter and the Rust projector. The report pins the LLVM
library and source file digests. The Rust harness can be extracted from the
native projector receipt. [Projector source and build instructions](https://github.com/astral-experiments/ohm/tree/bdbedd3a3fefada3387d25792a4c4cd0d01f9170/scripts/ruff-cgu-debug-locations/evidence/41371190920/native)

```sh
clang++ $("$LLVM_CONFIG" --cxxflags) -O2 -DNDEBUG -fPIC -shared -Wl,-z,defs \
    "$RUST_SOURCE/compiler/rustc_llvm/llvm-wrapper/OhmSourcePlacement.cpp" \
    "$SIGNED_LLVM" -o wrapper.so
python3 -IB emit.py --llvm "$SIGNED_LLVM" --wrapper ./wrapper.so
python3 -IB verify.py --projector "$RUST_PROJECTOR"
```
