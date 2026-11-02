# Ruff release checks for the two Ohm 1.99.0-23 packages

The Linux package from #253 eliminates 53 of the 103 links that the earlier package performed on an unchanged Ruff workspace. The 50 remaining destinations are exactly those seen on signed Ohm -18. Both packages used Wild 0.11.0. [Earlier package](https://github.com/astral-experiments/ohm/pull/228) · [New package](https://github.com/astral-experiments/ohm/pull/253) · [Per-target destinations](destinations.tsv)

| Same unchanged workspace command | Earlier #228 | New #253 |
| --- | ---: | ---: |
| Cargo products | 619 | 619 |
| Products Cargo reported dirty | 133 | 56 |
| Full rustc invocations | 22 | 1 |
| Link-only rustc invocations | 83 | 50 |
| Physical Wild links | 103 | 50 |
| Original -18 destinations linked | 50 | 50 |
| Additional destinations linked | 53 | 0 |

Both workers built Ruff at commit `93526150df078af7dd8fc4226cdcc469539d2001` with `cargo +ohm test --workspace --no-run --locked --offline -j8 --message-format=json`. Cold, ordinary unchanged, traced unchanged and fingerprint-logged unchanged visits recorded Cargo's typed artifacts and their physical outputs. Each link joins a successful Wild exec to its rustc parent, its `-o` path and its Cargo target. A rustup proxy and the compiler it launched in the same PID count as one compiler. [Earlier workspace](https://github.com/astral-experiments/ohm/actions/runs/41446263214) · [New workspace and native controls](https://github.com/astral-experiments/ohm/actions/runs/41450882756)

On the new package, `ron` was the only full compile. All 50 links reported a changed upstream fingerprint. Thirty-five read the `ron` archive directly. The remaining 15 inherited the dependency change. Every file that both appeared literally in those 50 linker argument lists and was hashed as a Cargo product kept the same bytes across all four visits. The archive and standalone Rust metadata need separate treatment. The complete `ron` archive stayed identical, while the standalone metadata changed in two of three transitions. Each link also had at least 34 absolute file arguments outside Cargo's product table and seven symbolic libraries. [Machine-readable observations](observations.json)

## Real edits

A Ruff renderer fix changed two products on both packages, the renderer and the `ruff_db` library test. The old executable differed from the edited one. The edit, both unchanged repeats and an independently empty build produced identical new executables. The test inventory had 126 names and both selected renderer snapshots passed. The earlier package repeated one link on an unchanged command. The new package kept all 171 products fresh and ran zero linkers. Its actual rustc work-product tables also showed 180 of 218 test codegen units retained across the edit. Thirty-eight regenerated. [Ruff renderer change](https://github.com/astral-sh/ruff/pull/27470) · [Earlier renderer run](https://github.com/astral-experiments/ohm/actions/runs/41441340483) · [New renderer run](https://github.com/astral-experiments/ohm/actions/runs/41450882756)

A separate `ty_server` change added a real e2e case. Both packages compiled the changed library and test. The new implementation reported a warning. Putting the historical implementation under the new test reported an error and failed the assertion. An invalid Rust edit failed with E0308. The edited, repaired, restored and independently clean executables matched byte for byte. The earlier package repeated the link on an unchanged command. The new one kept all 302 products fresh. Its three distinct executables were also extracted from the original artifact and run on a second Linux machine, including the expected failing historical control. [Ruff e2e change](https://github.com/astral-sh/ruff/pull/27836) · [Earlier e2e run](https://github.com/astral-experiments/ohm/actions/runs/41448240223) · [New e2e run](https://github.com/astral-experiments/ohm/actions/runs/41450882756)

## Native library changes

Two real ELF libraries with distinct SONAMEs and runtime witnesses occupied the same SDK library-search slot. The replacement preserved the device, inode, size and mtime. Under #228 the unchanged command selected the physically present library and rejected a malformed replacement. Under #253 these undeclared changes kept the previously linked executable. Adding A preserved the system-linked executable, replacing A with B preserved A, and the malformed replacement also preserved A. Forcing a fresh link with the malformed file failed with exit 101. After repair, the executable ran B and matched the clean build. This is the declared-input policy in Cargo #424. Its separate Linux and macOS tests cover changes to declared static libraries. [Earlier native controls](https://github.com/astral-experiments/ohm/actions/runs/41444949106) · [New native controls](https://github.com/astral-experiments/ohm/actions/runs/41450882756) · [Cargo #424](https://github.com/astral-experiments/ohm-cargo/pull/424)

## Reproduction

The packaged Linux source pins are Rust `a21de69d085aa07b3b5ac94058bac9e5aed482b4` and Cargo `4109dd69209a642f309555cac0cee8b05e18f0ea`. The SDK came from artifact `13144147426` with SHA-256 `3de34fa8799dbc8f05069bf7916012597061a9adc69b0ff0898aca936d16ee68`. The qualification worker ran at `1d6b3796f659359efb9ab9dfc6c0cf860eb9f1ee`. Its original ZIP, artifact `13144224899`, has SHA-256 `37b4aac76dce38c4d84c51cf17d39857f96fc1860e8d9d3456f8ba89e553ca7d`. [SDK build](https://github.com/astral-experiments/ohm/actions/runs/41442788155) · [Pinned worker source](https://github.com/astral-experiments/ohm/tree/1d6b3796f659359efb9ab9dfc6c0cf860eb9f1ee/scripts/ruff-db-link-reason)

From an authenticated Ohm packaging checkout on the devbox, the following repeats all four checks while the original SDK artifact is available.

```sh
ohm_repo=astral-experiments/ohm
qa_branch=charlie/qa-ruff-db-link-cause-20261102
gh_auto=/home/dev-user/.local/bin/gh-auto
qa_revision=$("$gh_auto" api "repos/$ohm_repo/git/ref/heads/$qa_branch" --jq .object.sha)
"$gh_auto" workflow run ci.yml --repo "$ohm_repo" --ref "$qa_branch" \
  -f "reviewed_head=$qa_revision" -f distributions=rc253 \
  -f native_witness=true -f whole_workspace=true -f ty_edit=true
```
