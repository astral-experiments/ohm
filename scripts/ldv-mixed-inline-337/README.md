# Inlined variable locations in a line-table function

The exact parent and candidate from [Ohm Rust #337](https://github.com/astral-experiments/ohm-rust/pull/337) both let GDB read `inline_witness = 22` inside `full_inlined`. The emitted object and executable matched byte for byte across compilers. Disabling LLVM's range propagation made GDB report `<optimized out>` at the same instruction on both builds. All four objects contained identical machine code, and all four executables passed 66 pairs of branch and input values.

The fixture supplies one LLVM module with two debug compile units. `line_inline` has a line-table root and a surviving variable inlined from a full-debug function. `full_branch` and `pure_line` exercise the other two paths. The original compiler factory supplied both measured rustc drivers and their common LLVM. The harness verifies the module, calls the compiler's actual output-pass factory and checks its concrete virtual table before emitting the object. A GDB trace identified the module's LLVM Function pointers at the pass entry points. The candidate delegated `line_inline` and `full_branch` to LLVM and skipped propagation for `pure_line`. [Source factory](https://github.com/astral-experiments/ohm/actions/runs/41425541148) · [Whole-Cargo instruction measurements](https://github.com/astral-experiments/ohm/actions/runs/41442005889)

Parent `1589b5884e0a690776147e3a72223843ab83dccb` and candidate `531eb1980c08c75ccbf3f6b77adbee53cd9b8bd5` produced object `37a14cb2ab3a898312db29e974247f862b31575a516d449b3c2589d06de5a4e1`. The inlined variable occupied RBX over `line_inline+0x6..0x1c`. The control set LLVM's two existing range-extension limits to zero and produced `b37dd1ecb9b6301cdf33bee29764f05f2045c73cfe0729481d39749f3ae0e1c6`, which carried neither variable location. This is an adversarial test of the output subsystem using constructed LLVM IR. It supplies no instruction-count observation.

## Replay

On x86-64 Linux with Python 3.11 or later and llvm-dwarfdump, this command checks the saved objects, runs the four original executables and verifies the two debugger outcomes and the guarded call trace.

```sh
python3 verify.py
```

To regenerate the objects, copy the source files into an empty scratch directory. Use the OSS GitHub account for the factory artifact, which is subject to Actions retention. The public receipt includes the original native outputs.

```sh
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13131394450/zip > source-sdk.zip
python3 prepare.py source-sdk.zip
export GLIBC_TUNABLES=glibc.rtld.optional_static_tls=262144
for role in P C; do
    for mode in ordinary disable-range; do
        python3 emit_mixed.py "$role" "$mode"
        cc -std=c11 -O0 -g0 -no-pie mixed-caller.c "$role-$mode.o" -o "$role-$mode.exe"
        "./$role-$mode.exe"
        gdb --batch -nx -q -iex 'set debuginfod enabled off' -ex 'set disable-randomization off' \
            -ex 'break *line_inline+0x14' -ex run -ex 'p inline_witness' --args "./$role-$mode.exe"
    done
done
OHM_MIXED_CONTACT=1 gdb --batch -nx -q -x contact.gdb.py --args /usr/bin/python3 emit_mixed.py C ordinary
```

The first local GDB attempt stopped at the sandbox's ptrace permission check. The first pass observer also refused the fallback argument because it read the register for a scalar-returning method. The corrected observer accounts for the hidden structure-return argument and binds each hit to the original named LLVM Function pointer. Only the completed debugger runs appear in the receipt.
