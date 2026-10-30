# External native providers with a register-only CRC instruction

Compare Rust `444c0273a2e2bc0b161e988d43c882349bc2d7a6` and `82911b516fb35608fd70ada4deb6f8429277f410` on Apple Silicon using the same signed Ohm 1.99.0-20 Cargo and Xcode linker. Each command builds one executable with an external static archive, with a single `crc32w` instruction either directly in that executable or in a non-inlined library it calls.

Run every combination of the two compilers, both placements, both watch policies and Cargo defaults enabled or disabled. Each build script adds two native search directories in the same order. The declared case watches both. The unwatched case watches only the build script itself.

Start with the lower-priority archive returning 17. Insert a higher-priority archive returning 29, corrupt it, remove both providers, then restore a valid archive. Interleave real Rust edits to a separate dependency. Keep the actual Cargo exit, test-program exit and stdout, Mach-O bytes, build-script output, compiler dep-info, and kernel exec streams. Compare every warm state with a separate empty build at the same paths. Classify unwatched native changes separately from declared inputs and genuine Rust edits. This experiment collects no timings.
