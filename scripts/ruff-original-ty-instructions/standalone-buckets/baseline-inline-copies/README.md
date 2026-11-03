# Outlined inline-copy inventory

This offline inventory addresses whether the existing P compiler emits the same function locally in a genuinely dirty CGU and provides a linkable definition for that exact symbol in another CGU. The registered inputs are the complete authenticated parent ty_project OLD/NEW .rlibs from both Ruff library builds. The compiler used opt-level 1, LTO off, disabled embedded bitcode, debug assertions and line tables. It emitted the normal LLVM pipeline.

Preserve ELF symbol binding, visibility, function ranges and section-relative relocation targets and addends. Count all private Rust and native functions as a conservative initial population, even functions internalized after root placement. An external ELF definition elsewhere is a candidate for source examination. A same-name private body in another CGU cannot satisfy a cross-unit reference as emitted. Report both kinds of matches. Count overlapping symbol ranges only once when reporting bytes. Neither emitted bytes nor MIR size estimate is a retired-instruction price.

A real three-object control contains two private functions, a strong owner with matching text, and identical call instruction bytes reaching different named symbols. It exercises both non-interchangeable relocations and the absence of an owner.
