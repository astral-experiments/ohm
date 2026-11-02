# Native code generation after a Ruff settings edit

Six of the 21 codegen units that Rust rebuilt on Ruff #28106 still took ordinary LLVM code generation with the guarded source-placement compiler. This diagnostic measures their actual cost on its parent compiler. The frozen edit changes `ruff_workspace` at `3c77dcc2` to `088b7b5f`. The command is `cargo +ohm build -p ruff_workspace --lib --locked --offline -j4`.

The first invocation uses the ordinary source-built parent from factory 41475100027. The second starts from the same Cargo target, build directory and registry state with the same bytes, mtimes and hardlink groups. A wrapper adds rustc’s retired-instruction profiler to the one edited library invocation. Both runs must compile the same 21 real units and produce the same 125 complete native objects, linked consumer and runtime verdict. The ordinary operator also runs an independent clean build and the type-error and repair history.

Only after those gates pass does the reader open the per-module optimizer and native object emission events. Each interval retains its own thread and start and end counter. Object emission is nested inside total code generation. The two measurements are reported separately. This diagnostic ranks remaining work and supplies no new whole-Cargo performance claim.
