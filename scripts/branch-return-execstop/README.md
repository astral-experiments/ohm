# Cold Ruff worker qualification

This branch runs one uninstrumented empty reference and one kernel-observed empty build on the exact same Koff installation. Both use the 169-path study's original parent Ruff checkout and default Cargo flags. The comparison covers all 375 returned artifacts, the actual 147 MB Ruff command-line program, its independent typed AST reader, and the compiler and linker processes. The worker never acquires a performance counter. Its native stream remains useful for diagnosis if the positive observer refuses.

The physical enrollment is recorded in `source-kit.json` and `historical-sources.json` in the inherited `../branch-return-pmu` tree. `cold.json` comes from the original successful cold Foff and Koff visits on different hosts. The full old pilot on those hosts subsequently stopped on a different gate. Both cold visits report the same 375-unit graph, 379 actual Rust compilations, 69 Wild links and 62 configure links. Exactly four Rust invocations came from the locked autocfg library. Its `new_crate_name` method uses an arbitrary UUID and a probe ordinal. The new checker binds the generating package, its actual out directory, contiguous owner-specific ordinals, LLVM-IR emission and physical rustc. No compiler rows are removed.

The Linux observer is an unprivileged ptrace parent. Each successful exec contributes an installed executable FD, full NUL-delimited argv, working directory, AT_EXECFN and task lifetime. An ordinary errno or a task killed while a requested exec is still pending remains distinguishable from a successfully installed program. The native fixture uses an actual invalid-address exec blocked in seccomp and killed before installation. Loss or corruption of an image, argv, lifecycle or completion record fails its own decoder. A shebang's physical image is the actual interpreter. Its requested script spelling and installed arguments are also recorded.

The original kernel ledger is `observed/cold-A/kernel.tsv.gz` in the extracted artifact. Its enrolled executable identities are in `observed/catalog.json`. The full live observer and native fixture ELF are under `fixtures/`. The role selection, complete Cargo streams, native evidence and independent current-host ELF bodies are nearby. The comparison does not require an old Cargo output's inode or path to match across hosts.

On Linux with Python 3.11 or later, zstd and b3sum, verify the extracted original using this checkout.

```sh
python3 -IB scripts/branch-return-execstop/reopen.py /path/to/extracted/artifact
```

To regenerate the two original cold compiler/link rosters and validate the separate application-specific negative tests, run these from the packet directory.

```sh
python3 -IB history.py /path/to/41200174886-01-13042772691.zip /path/to/41200174886-02-13043111933.zip | cmp - cold.json
python3 -IB test_projection.py
python3 -IB qualify.py --preflight
```

To run only the local event fixtures, provide two absent absolute paths under an existing, owned private directory. This needs Linux x86-64, a C compiler, OpenSSL development headers, working unprivileged ptrace and no Ruff SDK.

```sh
RUNNER_TEMP=/tmp python3 -IB fixtures.py /path/to/new-tools /path/to/new-receipts
```
