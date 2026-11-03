# The native inputs of one real Ruff test harness

On the signed Ohm `-23` Linux toolchain, stock Wild 0.11.0 loaded **409 files** for Ruff's `ty_server` e2e integration test. The kernel trace identifies an actual open and file-backed mapping for every one. It also identifies **86 failed direct library probes and eight failed nested script probes**. Neither stock reporter included those failed probes. Adding one file to the first search directory changed the actual library selected. These results concern the single executable on one controlled worker. [Complete acquisition](https://github.com/astral-experiments/ohm/actions/runs/41658029321) · [Original input and status](original.json) · [Source paths and prior Ohm work](SOURCE.md)

The ordinary virtual-workspace `cargo +ohm test --no-run --locked --offline -j4` built 102 test executables on the genuine [Ruff #29697](https://github.com/astral-sh/ruff/pull/29697) edit. The chosen executable was `e2e-f5c6198f896cf7b0`. Its complete OLD image was 227,977,696 bytes with SHA-256 `f203086dc58594dc33899d25dcbdcd5ec86d04e3dfb493efe7c7a59f6abd97e2`. The edited, observed, standalone stock, syscall-traced, and fully restored NEW images were all 227,979,336 bytes with SHA-256 `86b94323a752a316a501f542a846408648ca8b74c56bc60298690b671b7b0563`. A separate empty-target NEW build produced that entire ELF. The reader decompressed and hashed both full original executable bodies independently. All ordinary images listed the same 200 tests. OLD failed the edited `commands::debug_command` snapshot, and each healthy NEW image passed it. All runtime verdicts were taken outside the Cargo build. [Independent empty build](https://github.com/astral-experiments/ohm/actions/runs/41617756983) · [Original whole-body digests and file joins](all-inputs.json.gz)

| Argument | Failed candidate paths | Successful search directory (zero-based) | File |
| --- | ---: | ---: | --- |
| `-lgcc_s` | 10 | 5 | `libgcc_s.so` |
| `-lutil` | 13 | 6 | `libutil.a` |
| `-lrt` | 13 | 6 | `librt.a` |
| `-lpthread` | 13 | 6 | `libpthread.a` |
| `-lm` | 12 | 6 | `libm.so` |
| `-ldl` | 13 | 6 | `libdl.a` |
| `-lc` | 12 | 6 | `libc.so` |

The source and kernel records agree on the first successful candidate in each directory search. Each winner was statted successfully again later. Seven further files entered through the resolved libraries and scripts, including `libgcc_s.so.1`, `libgcc.a`, `libm.so.6`, `libmvec.so.1`, `libc.so.6`, `libc_nonshared.a`, and `ld-linux-x86-64.so.2`. The five startup objects on which the earlier worker could not acquire a read lease were each opened and mapped once. The sixth path, `liblto_plugin.so`, appeared in GCC’s arguments and had zero opens and mappings on this Rust link. The two built-in reports listed the same 409 distinct positives, including the physical named `symbols.o`. The earlier library search failures can be reconstructed only from the separate syscall observation in this experiment. [Every ordered lookup and file-backed range](verified.json.gz) · [Earlier read-lease census](https://github.com/astral-experiments/ohm/actions/runs/41627259427)

The exec observer copied rustc’s disappearing **39,760-byte `symbols.o`** before Wild ran. Stock mapped all 39,760 bytes. Its SHA-256 was `686f6a2749ab0d980e5627e5568850d2a8d8e79e480d6d62499241056036873d`. A valid archive in the first `-L` directory replaced the system `libutil.a`, reduced failed direct probes from 86 to 74, and initially produced the exact same runnable ELF. Changing only bytes 8731–8734 in the real temp object renamed its one global undefined `main` to `zzQA` among 348 ELF symbols. File size, inode, mtime and all other object bytes were preserved. The earlier archive now contributed an initializer. The newly linked ELF hash was `8c579fff30074179355f18b92e83ef24ba7649894dfd6b456f11fe306873eeb6`. It exited 83 before listing any tests. Restoring the four bytes restored the whole NEW ELF with the archive still present. Replacing that one earlier archive with malformed contents caused a real Wild error and produced no executable. Removing it restored the entire independent-clean NEW ELF and passing test. [Native experiment](../measure.py) · [Symbol table and offsets](all-inputs.json.gz)

The original 446 argument strings from the current and earlier workers differ at 373 positions. Their search and file roles agree after accounting for the two Cargo output-directory identifiers, retained codegen object session suffixes, rustc temp directories, and GCC resolution temp paths. An independent check of the earlier positive-file digests found genuine byte differences in **68 of the 395** prior surviving operands. All 68 were equal-length `.rlib` files. Full cross-worker input identity therefore fails. All challenge comparisons used the current worker’s own original inputs, with complete output bytes and behavioral gates. The receiver’s first stricter literal cross-worker argv check was recorded as a refusal. The original kernel rows also contain a second successful stat of each winner late in the link. The reader verifies both sightings separately. [Original kernel and prior-SHA joins](verified.json.gz)

A safe pre-link skip still needs a coherent current observation of earlier candidate paths, the recursive script choices, the bytes of selected files, and the transient object as rustc generated it. Reopening previously successful names cannot detect the new earlier provider. An open and a mapping prove which path the kernel served during this controlled link. Concurrent replacement, modification of mapped bytes, or changes while declaring a later target fresh require additional guarantees. The five system-file mappings are evidence of true reads, and their positive identity remains an open production problem. This run claims no performance gain. [Exact compiler and linker boundaries](SOURCE.md)

## Reopen the originals

Use Python 3.11 or newer with the `zstandard` module. Run from a copy of this evidence directory with write access. The script checks the three published complete ZIP SHA-256 values, including the outer GitHub digests. `reopen.py` and `enrich.py` write uncompressed verification reports.

```sh
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13239934582/zip > current.zip
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13226747746/zip > prior-inputs.zip
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13223081435/zip > independent-workspace.zip
python3 -IB reopen.py current.zip f77b1c66e8f1b45a6cec697c95aeca74409bed9dc2801f217eacd2ac9310c344 41658029321 41dcfc21d44e5330a936352771104c2925cd217b prior-inputs.zip
python3 -IB enrich.py current.zip independent-workspace.zip
python3 -IB controls.py current.zip
```

The negative reader controls remove one preceding unsuccessful lookup, change a real `ENOENT` to `EACCES`, or drop the kernel's `symbols.o` mapping. Each corrupted original is refused. [Raw negative-control results](reader-negative-controls.json)
