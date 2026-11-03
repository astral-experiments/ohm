# Private GNU compiler build for uv #21577

This job builds one corrected treatment. The control is the verified same-source rebuild of signed Ohm 1.99.0-23 from run 41615634254. Its original archive and native gates are recorded in `accepted-control.json`. Run 41619498528 provides a separate control for the original change to rustc_driver. Its GNU dynamic-link evidence and the two source issues requiring correction are recorded in `previous-treatment.json`.

The worker verifies the four signed release source trees, applies the registered Rust packet and runs the official x86_64 GNU stage-2 distribution with PGO training, ThinLTO, BOLT and Wild. It copies the pre-BOLT ELF, the compiler's closed exception lists, the actual GNU linker argument vectors and the stage's GNU linker wrapper while they are live. Native tests use the archive's compiler and the original signed Cargo executable.

`rc23-21577-fixed-source-dist-T` retains the original distribution before native qualification. `rc23-21577-fixed-source-qa-T-attempt-1` carries the source, build and capacity records, installed-file manifests, both ELF inventories, the native regression results and the actual interposition checks. Both archives have to pass independent local verification before a measurement can use this treatment.
