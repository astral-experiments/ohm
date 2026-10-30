These are two equally sized LLVM IR instrumentation profiles generated from the exact checked-in main.rs on the signed Linux Ohm 1.99.0-20. The program runs choose_slot 100,000 times with even or odd input. The function carries an unmangled name across stage-1 builds. The independent empty builds must prove these inputs actually change its complete native object. Run from this directory with payload.bin containing one byte (17).

```sh
rustc +ohm main.rs --edition=2021 --crate-name same_input -Clto=off -Copt-level=2 -Ccodegen-units=16 -Cdebuginfo=0 -Cprofile-generate=raw -o train
LLVM_PROFILE_FILE=even.profraw ./train 0
LLVM_PROFILE_FILE=odd.profraw ./train 1
llvm-profdata merge even.profraw -o 0.profdata
llvm-profdata merge odd.profraw -o 1.profdata
```
