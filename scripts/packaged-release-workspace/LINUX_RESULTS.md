# The original 50 Ruff links on published Ohm -20 and -21

On both unchanged commands, `-21` still ran one full `ron` compile and linked every one of the 50 original x86-64 Linux destinations. This includes all 49 whose ELF files had compared equal on the original first unchanged command. The 15 links removed since `-20` were outside this set. The 50 entries are matched using package, target, kind, test-profile bit and source path.

| Genuine workspace command | Full rustcs, -20 / -21 | All Wild links, -20 / -21 | Original 50 linked, -20 / -21 |
| --- | ---: | ---: | ---: |
| Cold original | 623 / 623 | 188 / 188 | 50 / 50 |
| First unchanged | 96 / 51 | 65 / 50 | 50 / 50 |
| Reverse the three-file trivia edit | 119 / 111 | 75 / 75 | 50 / 50 |
| Restore the edit | 119 / 111 | 75 / 75 | 50 / 50 |
| Settled unchanged | 96 / 51 | 65 / 50 | 50 / 50 |

No link-only compiler ran on these commands. Both independent empty builds reproduced the cold native counts. The command returned the same 102 executable identities, including 84 test programs, at every successful step. The recorded workflow counts actual compiler and linker processes and has no wall-time endpoint. [Frozen public Ruff source, exact command and edit](https://github.com/astral-experiments/ohm/blob/f40b16cdb9c041c941a5e339f816111a80a84bdf/scripts/packaged-release-workspace/LINUX.md) · [Native paired run](https://github.com/astral-experiments/ohm/actions/runs/41114085548)

The `ty_server` executable is the `e2e` integration target at `crates/ty_server/tests/e2e/main.rs`. Its own compiler and Wild both ran once at each edit and unchanged step on both releases. The 200-test catalog was stable. The real `pull_diagnostics::on_did_open` test passed with its tracked snapshot and failed with a missing snapshot. Both actual trivia library consumers printed the changed text after reversal and the original text after restoration. The independent empty original and reversed e2e executables differ on both releases. Restored and original e2e binaries are byte-identical. The Linux trivia reversal and Apple `ty_server` edit have different test catalogs.

Of 250 same-release, same-source full ELF comparisons, 242 on `-20` and 239 on `-21` matched byte-for-byte. The edited e2e is one of the exceptions on each release. Each differing pair changes the GNU build-ID descriptor and `.rodata.sh_entsize` in the non-loadable section-header table. Every other byte matches, including `.rodata` and all executable code. The original whole-file verdicts remain recorded. This field and build-ID signature was previously reported for shipped Wild. These packages both use Wild 0.11.0. [Wild #78](https://github.com/astral-experiments/ohm-wild/issues/78) · [Wild #79](https://github.com/astral-experiments/ohm-wild/pull/79)

The two compact receipts contain all 50 logical IDs, the actual `ron` and e2e compiler PIDs, e2e linker output paths, and the exact original differing ELF field values. The portable verifier reopens the captured kernel processes, Cargo results and ELF controls from each per-release ZIP. It validates both the complete original ZIP and its checked-in receipt.

```sh
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13005582402/zip > ruff-50-linux-20.zip
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13005843628/zip > ruff-50-linux-21.zip
python3 -IB scripts/packaged-release-workspace/linux_release_result.py 20 ruff-50-linux-20.zip
python3 -IB scripts/packaged-release-workspace/linux_release_result.py 21 ruff-50-linux-21.zip
```

The original `-20` ZIP is 398,515,914 bytes with SHA-256 `170b1a016fee38fb31a9fbfdb0f611212b00857e91d4b62647ce5b171ccedee7`. [Original -20 archive](https://github.com/astral-experiments/ohm/actions/runs/41114085548/artifacts/13005582402)

The original `-21` ZIP is 348,899,124 bytes with SHA-256 `cd0c0285bcb1d49f6560d9507f42fc06e1d69ee82c9f1e85cbf88473040fc953`. [Original -21 archive](https://github.com/astral-experiments/ohm/actions/runs/41114085548/artifacts/13005843628)
