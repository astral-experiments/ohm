# Compact build artifacts

Ohm builds that include the compact-capable Wild fork support an opt-in format for
smaller Rust build artifacts on native `x86_64-unknown-linux-gnu`:

```sh
cargo +ohm -Zohm-compact-artifacts=yes build
cargo +ohm -Zohm-compact-artifacts=yes test
```

The option is disabled by default. It selects the matching bundled Wild linker,
including when `-Zohm-defaults=no` is set. A toolchain without that linker reports
an error before compiling. Published toolchains predating this option do not
support it.

Rust libraries remain self-contained `.rlib` archives with full, directly readable
Rust metadata. Their object members and incremental object files are compressed.
They follow the existing target and shared build-directory lifetimes; no separate
object store or garbage collector is required. Switching the option on or off
selects distinct cached artifacts. `cargo clean` retains Ohm's normal shared
registry cache while removing the workspace's artifacts.

Final executables and shared libraries use ordinary ELF. Rust `staticlib` exports
contain ordinary objects for native consumers. An ordinary invocation of the same
Ohm compiler can materialize compact dependencies for a system linker, including
doctest links. Copying an `.rlib` requires no additional object store or metadata
sidecar; its other crate and native-library dependencies still apply.

The initial option requires the bundled Wild linker and full embedded metadata.
Cross-compilation, cross-crate LTO, linker-plugin LTO, packed split DWARF, explicit
linker selection, and conflicting artifact-format flags produce an error. Ordinary
native-library and rpath arguments are supported. The default compression profile
is `fast`; explicit compression tuning is preserved.

The [shipping evaluation](../scripts/benchmark_results/compact-artifact-shipping/README.md)
records the tested revisions, storage and timing results, and adoption decision.
