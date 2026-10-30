# Apple native-provider compatibility on the shipped Cargo lineage

This native APFS run exercises three Cargo executables on the same Apple-silicon host. The signed macOS -20 reader is `2d44bd4a`. The strict receipt reader is Cargo #293 at `735e1528`. The integration is `fd55a13d`, with signed #294 and the versioned #301 reader as its two parents. Its source-built executable SHA-256 is `9f09941432a849b13ee6177c2f4b0f35f5d9c350e518688d64325ce513ec532d`. The run also exercises the signed Rust producer, the versioned Rust parent and the published #281 compiler. [Native workflow and original artifact](https://github.com/astral-experiments/ohm/actions/runs/41110754345) · [Integration source](https://github.com/astral-experiments/ohm-cargo/commit/fd55a13d0220748794ba3c7c9556ef8ceed8591f)

| Native Apple observations | Commands | Outcome |
| --- | ---: | --- |
| Versioned parent and #281, direct and transitive providers, defaults on/off, watched/unwatched files and same-stamp replacements | 1,176 | Each reader passed every default and declared-input case. With explicit defaults-off, 12 untracked comparisons per reader differed from empty. The integration reused seven independently authenticated previous Xcode receipts. |
| Same-target receiver upgrades and downgrades | 72 | All default transitions returned the independent clean value or the same genuine error. |
| Actual registry zmij and zlib-rs | 12 | Both signed and #293 reran each crate on both repeats. With the new reader they stayed fresh. All empty/cold compiles emitted the v2 marker and all programs agreed. |
| Literal marker paths with real tracked-path proc macros | 72 | All v1, v2 and combined spellings stayed ordinary tracked inputs where the actual compiler recorded them that way. |
| Signed **old v1** Rust, direct/library, watched/unwatched, with an independently empty build for each visit | 264 | Signed and merged each differed from empty on six of 44 warm visits, with the same outcomes. Strict #293 detected all six. |

With old v1 and an unwatched native path, a new higher-priority archive left the cached program at `17 7` when clean returned `29 7`. Replacing the selected archive with malformed bytes or removing all providers left an executable in the warm target when the independent empty command returned Cargo 101. Both direct and library placements reproduced this. All six stale visits ran zero physical compilers and zero Apple linkers. All declared changes and all real Rust source edits and repairs had the clean outcome. The separate Linux experiment includes additional preserved-mtime transitions. The Apple v1 subset here covers insertion, malformed replacement, and removal. [Apple Unicode and Linux comparison](https://github.com/astral-experiments/ohm/tree/7680d2e9a617878d953977f1ebc8be3363671abb/scripts/ohm-gnu-syscall/evidence/release-reader-compatibility)

After these 1,596 commands the QA launcher failed to import a sibling module. It had executed zero timed `ty` commands. The Apple provider cases had separately closed and their originals were uploaded before that failure.

## Reproduction

Check the small projection with Python 3.11 or later.

```sh
python3 -IB verify.py
```

To recalculate every row, obtain artifact 13005066644 from the workflow linked above. Its original ZIP is 151,308,988 bytes, SHA-256 `21fa01ccb032337607407bb16b92161f5f04943b5b60c1d2e7521fb42b0499c5`. The full replay needs a local `b3sum` executable for Cargo's encoded receipt integrity checks.

```sh
gh-auto api --allow-escape-sequences repos/astral-experiments/ohm/actions/artifacts/13005066644/zip > apple-provider.zip
python3 -IB reopen.py apple-provider.zip
```

The original-file reader authenticates all 14,658 entries, reopens actual Mach-O images, native archive bytes, original CodeDirectory pages, CGU or linker operands, kernel exec records, depfiles, program output and error diagnostics, then regenerates the compact projection. Successful warm/empty comparisons retain full raw hashes separately from the narrowly normalized whole Mach-O comparison. Untracked, fresh and failing controls remain individually visible in the projection.
