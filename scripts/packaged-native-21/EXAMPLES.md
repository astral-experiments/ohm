# Packaged Apple Ruff examples

At Ruff commit aa9a1ff88aa83b3f01360ef5b3cb04b2be187206, build all twelve
examples with each physical packaged SDK. Use separate empty per-role target
and shared directories, one public checksum-verified registry, and Cargo's
ordinary developer defaults with CI and TF_BUILD absent. No clock is scored.

Use the public source unchanged for cold and both unchanged returns. Then
change only the real format example's diagnostic string, repeat, introduce a
genuine E0425 in that expression, and restore the original expression. Rebuild
old and edited in separate empty stores at exactly the same paths. Record
literal kernel Cargo, rustc, clang and Xcode ld execs and actual signed tool
identities. For regular results, preserve and run every Cargo-returned program,
retain its original bytes and streams and check all file-backed sections and
behavior against its own clean state. The raw complete-file differences remain
visible. Count a link only when the registered Apple ld has a physical output
and its actual clang and packaged rustc ancestors. For a Rust example the
native ld output must match the complete returned executable bytes. The
observer refuses an indirect linker argument file rather than inferring its
contents. All twelve cold examples must show a genuine -Cincremental and
finalized crate-specific dep-graph and work-products. No production changes.

The two installed archives follow the same immutable acquisition as the
separate private native-input release smoke at c07e8a560ce87969d70f11c0a59608b863da10b8.
For a retained QA archive, run the following from this checkout:

    python3 -IB scripts/packaged-native-21/examples.py read downloaded-original.zip

The original full-workspace link census used different compilers and Cargo
#293. These are separate runs on the shipped -20 and -21 toolchains.
