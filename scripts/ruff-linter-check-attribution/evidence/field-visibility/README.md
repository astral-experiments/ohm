# Field visibility in four crates on Ruff #28444

The D211 message edit still launched four rustc processes with both compilers. The candidate reduced the number of changed public definition hashes from 34,678 to four. The remaining four belong to the linter. We stopped before instruction benchmarking because the prospective gate required an indirect consumer to stay fresh. [Ordinary P/C qualification](https://github.com/astral-experiments/ohm/actions/runs/41569845446) · [Matched compiler factory](https://github.com/astral-experiments/ohm/actions/runs/41568934075)

The original Cargo command was `cargo +ohm check -p ruff_markdown --lib --locked --offline --message-format=json`. Git committed the change in Ruff at `04ae7c402b2a7f1c49a9a1dd264629c00e38f61b` on parent `64730be0c713bbc642c88e6824a386fa58452962`. Both roles used signed Ohm -22 Cargo at `ed0ae15d22da9a0af9afb3d0fdeb4ceb8a71b770`. The matching rustc source revisions are `259ad7069e47eaf08cf106f187b2b6393f7fd7c2` and `a7fc5bc7f90966e6e9a92f9239e3e304e79b2f3f`. Both roles passed the ordinary edit and a separate execve-traced repeat from the same pre-edit state. All 308 Cargo artifacts were fresh at both unchanged controls. [Ruff edit](https://github.com/astral-sh/ruff/commit/04ae7c402b2a7f1c49a9a1dd264629c00e38f61b) · [Registered workload](https://github.com/astral-experiments/ohm/blob/51f667c29b79a9a08010a04798e814d299877dff/scripts/ruff-linter-check-attribution/scope_inventory.py)

| rustc process | P changed public rows | C changed public rows | P edited metadata bytes | C edited metadata bytes |
|---|---:|---:|---:|---:|
| ruff_linter | 31,839 | 4 | 12,672,296 | 12,674,676 |
| ruff_graph | 167 | 0 | 96,969 | 96,986 |
| ruff_workspace | 2,656 | 0 | 993,868 | 993,868 |
| ruff_markdown | 16 | 0 | 26,015 | 26,015 |

The linter’s four changed rows identify `codes`, `registry`, `registry::INCOMPATIBLE_CODES` and the crate root. Each downstream public crate hash stayed identical across the candidate edit. Each downstream crate’s required-dependency table still recorded a new whole-crate `ruff_linter` hash. The candidate retained public rows for every restricted module found through the four crates’ visibility tables. P lacked 140 such rows in the linter and one in the graph crate. [Decoded full metadata report](report.json)

Cargo reads the public hash on the actual completed metadata file. Its early cutoff requires the local hash to match and every required metadata dependency to be safe. Changes to inherited metadata or a pending producer can affect a foreign trait implementation in an indirect client. Both the dependency guard and the source-level consumer are present in the measured Cargo source. [Cargo cutoff and transitive metadata check](https://github.com/astral-experiments/ohm-cargo/blob/ed0ae15d22da9a0af9afb3d0fdeb4ceb8a71b770/src/compiler/fingerprint/mod.rs#L1154-L1192) · [Foreign implementation regression test](https://github.com/astral-experiments/ohm-cargo/blob/ed0ae15d22da9a0af9afb3d0fdeb4ceb8a71b770/tests/testsuite/freshness.rs#L4673-L4857)

Both roles’ full edited Ruff executables matched the independently clean executable across compiler roles, including all 147,408,392 bytes. Edited SHA-256 was `6435c9ec8c4138c8584b08bcc5d7bfc658f4359075e85ba86346b045b5bc0038`. Old SHA-256 was `805b27d742793c22494a005ff36a5f8933b61e2e4e2e5f655cf8d74ac17c450a`. The executable reported the expected changed D211 warning and the D212 control. A real type error produced E0308 and the repaired source passed. Independently clean and warm metadata matched for 255/255 candidate artifacts and 227/255 original compiler artifacts. The control packet includes all their hashes, the real command events, the CLI verdicts and the original small native clients. The worker retained the large Ruff executable's digest and verdict. [Raw controls](raw-controls.tar.xz)

Ten paired private-scope, reexport, generic, scope-parent and real rustdoc-JSON checks matched their independent clean results. The private-field and uninhabited-field clients saw E0616 and E0004. Withdrawing the exact `ExactSizeIterator` implementation yielded E0277 and changing its associated item type yielded E0271. Old and repaired clients executed with outputs 11 and 19. Cross-version sessions verified the real RSIC 24450→49126 change and its inverse with held original native inodes, a changed client, E0308, repair and independently clean linked output. [Source fixture](../../scope_fixture.py) · [Foreign trait fixture](../../scope_adt_traits.py)

## Reopen

From this directory, run the permanent compact check with Python 3.11+, GNU cc, and a temporary directory that allows executing files.

```sh
python3 -IB verify_compact.py
```

To independently decode all original metadata bodies while the archived job is retained, run the following from this directory. Use a Linux x86-64 workspace, Python 3.11+, zstd, and a checkout of either matched Rust revision. The reader validates the symbol and table schema against their source digests. The two input Git references and installed-driver digests are bound in the factory manifest. [Factory bindings](../../scope-adt-factory.json)

```sh
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13200987254/zip > original.zip
python3 -IB make_receipt.py original.zip raw-repeat.tar.xz
cmp raw-controls.tar.xz raw-repeat.tar.xz
python3 -IB reopen.py original.zip 8474cc422216800f8a7fd467827f8afbe874cc1488f38aa1c97717b6eebc447f repeated.json --rust-source /path/to/matched/rust
cmp report.json repeated.json
```
