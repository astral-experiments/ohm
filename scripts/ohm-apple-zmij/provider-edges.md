# Apple native provider changes with a single vector-register comment

Compare Rust 2035696c5316079f5b2e4373aee834839aac97e9 with its direct child 444c0273a2e2bc0b161e988d43c882349bc2d7a6. Both use signed Cargo 2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c, matched stage-1 Rust and standard library, and Xcode's stock linker. This is a correctness study.

The fixture uses exactly one assembler statement, `asm!("/*{:v}*/", inout(vreg) vector)`. Place the function either in the actual executable or in a consumed Rust library. The executable prints the archive function and a separate, noninlined Rust dependency's value. Two Xcode-built Mach-O archives provide functions returning 17 and 29. The build script supplies the same earlier and later native search directories in both policies. The declared policy explicitly watches both existing directories and the build script. The unwatched policy watches only the build script. Repeat both placements and policies with default Ohm and with `-Zohm-defaults=no` under each Rust compiler. The command is an ordinary locked, offline Cargo build in the unmodified dev profile.

For each of these 16 installations run the following ordered states. Inspect the ordinary warm result. Park its three private Cargo state directories, then build independently empty at the identical source, driver, build, target and Cargo home paths. Restore the untouched warm state for the next visit. Source and archive files and their timestamps change only when the registered input changes.

| Visit | Native archives | Rust value | Expected on empty |
|---|---|---:|---|
| Lower, then an unchanged repeat | later 17 | 7 | 17 7 |
| Insert higher with no Rust edit | earlier 29 and later 17 | 7 | 29 7 |
| Real Rust edit | earlier 29 and later 17 | 11 | 29 11 |
| Malformed with no Rust edit | malformed earlier, no later | 11 | Cargo 101 with provider diagnostic |
| Real Rust edit while malformed | same | 13 | Cargo 101 with provider diagnostic |
| Restore valid generation before missing test | earlier 29 and later 17 | 13 | 29 13 |
| Remove both with no Rust edit | neither present | 13 | Cargo 101 with provider diagnostic |
| Real Rust edit while missing | neither present | 15 | Cargo 101 with provider diagnostic |
| Restore lower and genuine Rust source, then unchanged repeat | later 17 | 19 | 17 19 |

Keep every outcome. All declared and genuine Rust-edit verdicts must match their independently empty builds. Record unwatched native-only changes independently even when the compilers differ. Report complete byte differences separately when program behavior agrees. Retain every distinct complete executable, its `__text`, UUID and SHA. Compare original files within the same surrounding installation. Retain real Cargo JSON, stderr and exits, actual linker argv and output, and the selected unit's native depfile. Endpoint Security observes Xcode linker execution and search operands. The known archive functions and program output distinguish provider selection. The observer does not trace the linker's filesystem accesses.

Finish all states before the aggregate verdict. Record any parent-to-child change, including prior favorable behavior for a deliberately unwatched provider. Preserve native evidence on a rejected gate.
