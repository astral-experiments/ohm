# Ordinary Cargo after a real renderer edit

The candidate changes Cargo's executable-target eligibility check from `is_bin()` to `is_executable()`. This adds binary examples. Both programs retain release-22 Rust, standard libraries, GCC, and Wild. The pilot must first observe a real example's saved-codegen link, catch a Rust type error and a malformed native library, execute both changed native constructors, and match independent clean executables.

Measure two commands on the historical Ruff checkout at `93526150df078af7dd8fc4226cdcc469539d2001`.

```sh
cargo +ohm build -p ruff_annotate_snippets --examples --locked --offline -j4 --message-format=json
cargo +ohm test -p ruff_annotate_snippets --no-run --locked --offline -j4 --message-format=json
```

Each worker builds the original renderer from an empty target, applies the authentic two-file repair from `9c53b5de3aae4b1832eb7ee137647dda2466f888`, then measures the edited command, its first unchanged repeat, and a settled repeat. Each phase uses the original inherited hardware retired-user-instruction counter around Cargo and all its children. The edited and two unchanged commands run consecutively before anyone inspects the ELF files or build tree. Output and libtest inventory checks run outside the interval. Four fixed available CPUs and the same absolute source, target, Cargo, and registry paths apply to both arms.

Use six distinct GNU boots. Three start with the parent and three with the candidate. Every worker repeats both arms in reverse order, with an empty build directory for each history. Treat the six boot-level pairs as the independent observations. The primary endpoint for each command is the first unchanged repeat. Report the geometric mean candidate/parent ratio from the two within-boot pairs and across those six independent boots, all per-boot reductions, an exact paired sign-randomization test and a boot-resampled 95% interval. Also report the cold, edited, settled and edit-plus-first-unchanged effects. Register both workflows even when one does not benefit.

On one additional settled invocation per arm and workflow, preserve the kernel's actual Cargo, rustc and Wild argument vectors. For the twelve-example command, the parent must compile each example fully and the candidate must submit its saved `.rlink`. Wild must run for every target on both sides. Inventory the actual work performed by the complete test command. Compare the bytes of every executable example and test binary to an independent empty NEW build. Run every captured example and ask test harnesses for their complete test inventories outside the measured command.

Each history records apparent and allocated bytes, with hard links counted once over the private target and build directories. Report retained `.rlink` files, manifests, object-directory contents, and the total footprint both after the empty OLD build and after the unchanged NEW loop. Keep all six submitted runs, their original artifact digests and any refusals. A failed semantic, kernel or hardware guard is not a product speed measurement.
