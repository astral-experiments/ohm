# Why a Ruff workspace codegen unit rebuilt

The signed GNU build of Ruff's 169-path AST change emitted 49 workspace codegen units. The ordinary preoptimization bitcode and complete native objects of 48 units matched both revisions and independent empty builds. That archive contained no prior dependency graph or work-products table, so it could not explain the decision to recompile. [Original study](https://github.com/astral-experiments/ohm/actions/runs/41362345812)

The observer takes the incremental directory from the actual `ruff_workspace` rustc argv. In each of the ordinary observed and saved-bitcode histories, it freezes every completed workspace session after B, again immediately before the A command, and after A. It retains the dependency graph, the build and check graph checkpoints when present, and the work-products table. Every other regular file, including every possible donor object, has its exact filename, inode, timestamps, size and SHA-256 recorded. The two pre-A inventories must agree. Commit-pinned installers and the original Cargo histories check the changed, empty, invalid and repaired native outputs.

Graph indices identify nodes within an individual captured graph. Comparisons across compiles must use the dependency kind and 128-bit key and preserve duplicate entries. A prior graph and donor inventory can establish availability of previous inputs. Identifying the first rejected dependency also requires observation of the signed compiler's actual color or query-forcing decision.

This run is diagnostic. Its outcome is a physical reason for recompilation with the original branches and final products attached; it has no treatment or performance admission.
