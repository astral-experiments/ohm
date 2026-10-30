# AArch64 portable-atomic on the Ruff database build loop

The first twelve-pair hardware study measured a 10.0093× reduction in whole-command instructions on the first unchanged library build, 1.4773× on the actual edited build and 1.9072× for the two commands together. A second set of twelve new workers using independently source-built compilers and Cargo reproduced 10.0095×, 1.4770× and 1.9068×, respectively. [Draft compiler PR](https://github.com/astral-experiments/ohm-rust/pull/285) · [Primary result](evidence/primary-41141112097/) · [Independent reproduction](evidence/replication-41143416626/) · [Source qualification](evidence/source-41141810291.md)

Both measured cohorts use Rust source `4ed3e4d1`, with the exact compiler and standard-library Git trees of the original review commit `cfb92189`. Draft #285 later fast-forwarded to `adea62b6` to wrap one 101-column test fixture line. The only changed file was `tests/run-make/ohm-checked-dep-info/gnu_aarch64.rs`. Its non-whitespace bytes match exactly. The compiler tree remains `359e5df0ebc4613cedf4518a021a16790d94f7d5` and the standard-library tree remains `4f7a8f755164dc68fff80790db8a844ae030fd03`. [Commit and fixture comparison](evidence/review-head-adea62b6.json)

This baseline asks whether the usual Ruff library build, or its test executable, leaves enough work attributable to portable-atomic for a compiler optimization to halve the command's instruction count. It uses the original, independently rebuilt 119-member GNU AArch64 SDK from Ohm Rust #283 and Cargo #301. The signed -21 Linux package has a different compiler and ships only x86-64 Linux libraries. [SDK provenance and source reconstruction](../ohm-gnu-syscall/source-rebuild/)

Run the isolated screen on GitHub Actions.

```sh
gh workflow run ci.yml --repo astral-experiments/ohm --ref charlie/qa-gnu-atomic-ruff-db
```

The workers independently build the parent and actual one-file change from Ruff #27849. One runs `cargo build -p ruff_db --lib`; the other runs `cargo test -p ruff_db --lib --no-run`. Both select `--target aarch64-unknown-linux-gnu --locked --offline -j4 --message-format=json`. Two normal unchanged visits follow the edit. Each records every rustc execution, compiler classification, linker and Cargo unit. A separate settled visit registers the physical binaries and commands before one full Callgrind diagnostic. Raw profiles and independent Valgrind totals must agree. Single unpaired process counts give an attribution and a conditional ceiling if other work persists. They do not estimate the effect of a candidate. [Ruff fix](https://github.com/astral-sh/ruff/commit/49bf50b1c782a4e443ae3edce2fdb6d81c2df562)

An undefined symbol must produce E0425. Each worker builds again after a repair and from an empty private target and build directory. The test worker runs the positive AST round-trip and each new bounds test under QEMU, outside the compile observation. A final run keeps the new tests and restores the old method. Each regression test must then fail while the positive round-trip still passes. Warm and clean hashes are reported separately. Any mismatch retains both complete products for examination.

## Structural result

On the GNU AArch64 cross-target build of Ruff, the real AST bounds edit still compiled `ruff_db` with both compilers. Both unchanged library builds ran one full `portable_atomic` rustc with #283. The candidate ran zero rustcs. Neither compiler invoked a linker in those two library builds. A separate baseline-only diagnostic attributed 2,541,911,126 of 2,824,041,161 Callgrind instructions to the single `portable_atomic` compilation. [Fresh matched library build](https://github.com/astral-experiments/ohm/actions/runs/41140125827) · [Baseline process counts](evidence/baseline-build.json) · [Preregistered experimental design](registered.json)

| Actual work after the edit | #283 | Candidate |
| --- | --- | --- |
| 174-unit library, edited | Compile `portable_atomic`, compile `ruff_db` | Compile `ruff_db` |
| 174-unit library, first and second unchanged | Compile `portable_atomic` each time | Zero rustcs or linkers |
| 188-unit test, edited | Compile both crates and link the Ruff test | Compile `ruff_db` and link the Ruff test |
| 188-unit test, first and second unchanged | Compile `portable_atomic`, run link-only rustc and GNU ld | Run link-only rustc and GNU ld |

For `cargo test --no-run`, both compilers produced the same 28,189,264-byte AArch64 test executable after the edit, both unchanged visits, the malformed-edit repair and the independent, empty build. The old source listed 126 tests and the new source listed 129. The existing AST round-trip test and all three new bounds tests passed under QEMU. Restoring the old method while keeping the new tests made all three regressions fail and kept the round-trip test green. The separate invalid Rust edit failed with E0425. [Test jobs and archived sibling observer failure](https://github.com/astral-experiments/ohm/actions/runs/41139680344) · [Parent test evidence](evidence/test-P.json.gz) · [Candidate test evidence](evidence/test-C.json.gz)

The complete warm and empty `ruff_db` archives differed in metadata and archive member names on both compilers. All 216 AArch64 object bodies matched byte for byte within each arm and across arms when keyed by CGU name with rustc’s session suffix removed. A separate Rust program compiled against the actual archive and full compiler-produced metadata from each build. Its new 18,556,120-byte executable had SHA-256 `1463649e598b4d9d3d4c0431581ca17fa0cf3b3bb169380ce7dca05849160ce2` for edited, unchanged, repaired and clean libraries in both arms. The old executable was distinct. The independent program parsed Python with one and 65 statements, retrieved every valid node through Ruff’s public API and confirmed the corrected boundary diagnostic under QEMU. [External caller](consumer.rs) · [Parent archive and external ELF evidence](evidence/build-P.json.gz) · [Candidate archive and external ELF evidence](evidence/build-C.json.gz)

The candidate was built from the registered three-file product diff over #283. The two compilers have identical complete host and AArch64 libraries, Cargo and Wild. The driver grows by 28,592 bytes. The locked `portable-atomic 1.13.1` had 98 MIR assembly sites, with 81 distinct MIR templates and 26 distinct emitted LLVM templates. The recognizer admits whole statement shapes with typed register operands. A two-role guard run tested 47 assembler and same-crate native-link cases per compiler. It also ran ten normal Cargo builds per compiler using a nested assembler include, a same-size and same-mtime mutation from 17 to 29, malformed and missing inputs and a repair to 41. The valid, malformed and missing histories agreed with independent empty builds. [Bootstrap](https://github.com/astral-experiments/ohm/actions/runs/41138808306) · [Ruff’s enrolled MIR and LLVM](evidence/portable-atomic-1.13.1/) · [File and assembler evidence](evidence/guards.json.gz)

In a separate three-crate native-link control, an otherwise plain intermediate Rust crate bundled an unwatched native archive. The ordinary build on both #283 and the candidate kept returning the old value 17 after replacing the archive with a provider returning 29, and succeeded on a malformed provider. An independently empty build returned 29 or rejected the malformed archive. Forcing the intermediate crate to rebuild agreed with the empty build. Stock Rust/Cargo 1.99 reproduced the same failures. The registered confirmation addresses ordinary Rust edits with properly declared inputs. [Transitive provider study](https://github.com/astral-experiments/ohm/actions/runs/41139771526) · [Qualification and limits recorded before dispatch](confirmation.md)

## Inspect the witnesses

The five compressed JSON records contain the original compiler and LLVM identities, complete observed code-object hashes for the library, full test inventories, native verdicts, and process arguments for the edit and unchanged visits. The exact GitHub runs, head commits, jobs, artifact IDs and SHA-256 digests are fixed in `evidence/sources.json`. Open the recorded results offline with `gzip -dc`. The successful test jobs belonged to a mixed run. Its two library jobs rejected an external caller that supplied Salsa’s split metadata stub. The separate successful library run supplied both components to the same direct rustc entry point. The earlier isolated-import failure occurred before the Ruff workload. [First observer failure](https://github.com/astral-experiments/ohm/actions/runs/41139465449) · [Job and artifact identities](evidence/sources.json)

```sh
gzip -dc scripts/ohm-gnu-atomic-db/evidence/build-C.json.gz |
  jq '.report.snapshots["first-repeat"] | {units, full, link_only, links, consumer}'

# Reopen authenticated Actions ZIPs and compare the checked-in projections while the ZIPs are retained.
python3 -IB scripts/ohm-gnu-atomic-db/collect.py

# Repeat the structural pilot and the separate assembler/file controls on fresh workers.
gh-auto workflow run ci.yml --repo astral-experiments/ohm --ref charlie/qa-gnu-atomic-ruff-db -f phase=pilot
gh-auto workflow run ci.yml --repo astral-experiments/ohm --ref charlie/qa-gnu-atomic-ruff-db -f phase=guards
```

## Repeat the instruction study from source

Use a checkout authorized for the Ohm repository. The source phase builds Cargo #301, the #283 compiler and the candidate compiler from their registered Git trees. It installs both standard libraries for each compiler. All 119 SDK entries must reproduce their original checksums, sizes and modes. Each resulting SDK runs the real Ruff edit, invalid edit, repair and independent empty build. Two complete downstream QEMU executables, old and new, are retained once per worker for byte-level review. The bootstrap uses published compiler/CI LLVM components and the checksummed Ohm `-20` distribution. The compiled products cross only between jobs in the new dispatch. [Bootstrap and embedded source identities](source/source.json) · [Common compiler and Cargo reconstruction](../ohm-gnu-syscall/source-rebuild/) · [Checked assembly forms](evidence/portable-atomic-1.13.1/forms.json)

```sh
repo=astral-experiments/ohm
ref=charlie/qa-gnu-atomic-ruff-db
qa_commit=$(gh-auto api "repos/$repo/git/ref/heads/$ref" --jq .object.sha)
gh-auto workflow run ci.yml --repo "$repo" --ref "$ref" -f phase=source
```

Set `source_run` to the numeric ID printed above. After the source qualification succeeds, start the registered twelve-position holdout within four days, while that new run’s temporary parent SDK and candidate driver remain available. The two commands must select the same QA commit. A reviewer can start another source qualification at any time to regenerate the transfers. The holdout independently checks their run, QA commit, compressed digests and every uncompressed SDK member before measuring.

```sh
gh-auto run watch "$source_run" --repo "$repo" --exit-status
test "$qa_commit" = "$(gh-auto api "repos/$repo/git/ref/heads/$ref" --jq .object.sha)"
gh-auto workflow run ci.yml --repo "$repo" --ref "$ref" -f phase=holdout -f source_run="$source_run"
```

Set `holdout_run` to that second run ID, then collect the pairs while its seven-day job artifacts remain available. The retained text data includes the original hardware clocks and calibration, Cargo unit streams, external consumer hashes and verdicts, unchanged physical process traces and the target/build inode inventories. The offline command independently recomputes the twelve ratios, their order-statistic interval and the exact randomization test. Use `gh` in place of `gh-auto` on a machine where that is the authenticated GitHub CLI.

```sh
gh-auto run watch "$holdout_run" --repo "$repo" --exit-status
python3 -IB scripts/ohm-gnu-atomic-db/pairs.py collect "atomic-counts-$holdout_run" --run "$holdout_run" --head "$qa_commit" --source-run "$source_run"
python3 -IB scripts/ohm-gnu-atomic-db/pairs.py verify "atomic-counts-$holdout_run"
```
