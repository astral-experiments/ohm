# Read the native foreign-span observation on Ruff's RUF009 edit

This single-worker diagnostic builds Ruff commits 710c60f and b00f68a with the exact signed Ohm -23 Cargo/rustc pair. The standard Cargo entry is `cargo +ohm check -p ruff --bin ruff --locked --offline -j4 --message-format=json`. It compares two unchanged ordinary Cargo inventories, captures the actual ty_python_semantic compiler's argument vector and dependencies, and passively traces a private replay of the same signed rustc.

The receiver checks every native marker-store instruction before setting a breakpoint, takes real source file IDs and original in-process locations, and reads the original Debug return values. The independent predicate uses the Debug value's original hygiene context and absolute end position and the first imported file start in the original compiler's ordered source map. Every ordinary and replayed metadata byte and the dependency record with just its private output path normalized must agree.

The sealed controls require 299 total joins, two foreign joins on the real bitflags provider and 21 Debug entries. A Debug call with a genuine independent reason is a veto for a join-only shortcut if its inputs cannot also be validated. All work is outside performance clocks. The SDK archive and all 79 installed members are authenticated. Registry and Git dependencies come from the original Ruff lock. No trust override is enabled.

Reopen an extracted artifact using `python3 -IB scripts/ruff-foreign-span-observer/reopen.py /path/to/extracted/artifact`.
