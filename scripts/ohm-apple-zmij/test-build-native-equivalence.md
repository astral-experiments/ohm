# Comparing native Rust test executables across compiler builds

The first test-build qualification stopped on the clean parent before taking a timing. Libtest adds ` - should panic` to six real Ruff test names when printing their verdicts. The complete name set and the six expected successful panic-handled tests are checked on each run. [First attempt](https://github.com/astral-experiments/ohm/actions/runs/41052488154)

The second qualification compared all four complete clean Mach-O files and stopped before the first timing because their hashes differed across compilers. Each arm's edited, unchanged and repaired executable matched its own independent clean file. Both compilers ran the same 53 and 54 tests. Their complete machine-code sections matched for both source states. [Second attempt](https://github.com/astral-experiments/ohm/actions/runs/41053629169)

The raw ZIP of that attempt has SHA-256 `777a63bd3105370057ec66646b785b4b0e43926e2f17a4ade6d12f39ce5d44bf`. The two old-tree executables differed in 533 bytes. The two edited-tree executables differed in 548 bytes. Every differing byte belongs to one of two fields.

- The physical Cargo rebuilds use different 16-hex toolchain namespaces in the same workspace's output paths. The Mach-O string table contains these paths in N_OSO debug symbols. Each affected string names a physical object or an archive passed to the same Apple linker that produced the returned test executable. The workspace identifier, crate names, object names, archive member names and all other path components match.
- The linker generates an ad-hoc SHA-256 CodeDirectory over the executable. Changing the debug path changes the corresponding page hashes. Each independently recomputed original page hash must match its stored value.

The prospective comparison permits precisely the observed 16 hexadecimal bytes in those authenticated debug paths. In memory it then recalculates the verified page hashes and compares every byte of the resulting images, including all load commands, program data, instructions, symbols, signature headers, other page hashes and padding. Each warm executable must still match its own empty-build reference byte for byte. The actual executables are preserved and used for all tests.

The two mirrored pairs and independent twelve-pair order, measured commands, time endpoints, native provider controls, and 2× admission gate are the same as the previous untimed attempts.
