# Release Cargo with the two consumed-input compilers

The same 26 ordinary Cargo commands, 20 real consumer rustc invocations and three independent pairs of identical native executables passed on Linux x86_64 with Cargo built in release mode, thin LTO, one codegen unit, and the ohm-defaults and all-static features.

The older v4 reader, ba07041c, left a real poisoned consumer fresh. Replacing only Cargo at the same SDK pathname with the v5 reader from 4a6de785 made the first unchanged check run rustc and report E0308. The consumed file kept the same timestamp, pathname and bytes throughout the Cargo swap. The current reader rejected divergent consumed-byte observations reported by either C1 or C2, including two spellings of the same path. It kept the consistent-input controls fresh. Every repaired native program and its independently empty build printed `29 29`.

| Actual binary | SHA-256 |
|---|---|
| v4 Cargo, ba07041c | c67a662901b9d15945579f0b607c234cf92e55488c687b68ba8a95f9e22326a2 |
| v5 Cargo, 4a6de785 | f97b6020c860e05eb3b4a20f0d2ae0d0e1b10953bc2a2d2205b77df9565cb13d |
| C1 rustc driver, preserves the two raw spellings | d377ef6f819ac8dc5d200cc1ad435f76b00290e5bd2dfb83873b3e2f79d6a72c |
| Rust #347 C2 driver, folds the equivalent consumed paths | 401860d7243a9af2e02d9d51fa6f0565c3352de4962eae163023daf65ecb5599 |

To reopen all 114 bodies, the actual Make checksum entries, binary dep-info, every exec trace and all three native pairs, run `python3 -IB ../reopen.py --packet . --b3sum /path/to/b3sum` in this directory. The 199,944-byte zstd archive has SHA-256 `0fa6912877788231c83d735fca7ce6545700ef14107b2e92b39f52040d0a042a`.

To reproduce the live checks, use the two commands from the [parent fixture](../README.md), add `--release-prior` to both, set `CARGO_V4` to the ba07041c executable above, and pass the release 4a6de785 executable and its SHA-256 on the verify command. [Physical Cargo source-build kit and both binaries](https://github.com/astral-experiments/ohm/actions/runs/41606683189).
