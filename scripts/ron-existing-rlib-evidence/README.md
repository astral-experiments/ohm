# Ron, an existing archive, and the cost of proving native objects reusable

On the nonincremental registry Ron compile actually selected by the Ruff #29697 default workspace test build, the published Linux Ohm -23 compiler executed approximately 9.49 billion Callgrind guest instructions. LLVM optimization and object emission accounted for approximately 2.77B and 3.72B respectively. We kept resolution, proc macros, semantic checks, MIR lowering, current per-CGU preoptimization bitcode, the archive writer and Cargo's normal dep-info. An experimental native observer could use the ten matching object members of the ordinary existing Ron rlib. The experimental side receipt used 3,267 bytes (one 4 KiB allocation). It held no second native archive or serialized IR.

Each block started with an independent output and a counterbalanced P/C order. The charge includes both genuine processes, the software checks, the complete preoptimization serialization, archive member validation and ordinary output emission. Guest instructions are descriptive measurements of these individual compiler invocations.

| Per-invocation software check | Phase | Stock, block 1 | Diagnostic, block 1 | Stock, block 2 | Diagnostic, block 2 |
| --- | --- | ---: | ---: | ---: | ---: |
| BLAKE3 and held FD for signed rustc, driver and LLVM | Cold | 9,493,550,985 | 10,845,376,962 | 9,490,261,354 | 10,845,187,088 |
| Same | Unchanged | 9,490,753,262 | 4,413,219,110 | 9,495,494,149 | 4,410,525,643 |
| Independently rehash three software files with SHA-256 | Cold | 9,487,037,432 | 20,286,102,933 | 9,492,081,493 | 20,278,410,152 |
| Same | Unchanged | 9,492,041,071 | 13,846,804,919 | 9,494,190,517 | 13,844,069,759 |

The three-file held-FD treatment yielded 2.1505× and 2.1529× on unchanged Ron. Cold costs increased 14.24% and 14.28%. The SHA-256 treatment increased unchanged work by about 46%, despite avoiding the ten ordinary object emissions. The absolute distributions, individual compiler and supervisor counts, instrumented RSS, on-disk sizes and native event rosters are in `results.json`.

Both counters reopened every complete rlib and dep-info. The standalone metadata files were also decoded by stable definitions, expansion records and dependency fields. Physical anonymous lifetime definition indices may vary between successful stock compilers. The native control corpus covers a real Ron source edit, malformed and restored metadata/proc-macro inputs, codegen options, remapped paths, invalid LLVM, and an external assembly read. A changed executable generation during the attempt, including a forced kernel lease break on a private copy, required a fresh ordinary compiler. The failure and repair outputs are retained in `controls/`.

We subsequently observed nine more regular executable mappings in normal Linux rustc. They comprised 6,250,344 bytes of glibc, libstdc++, libgcc and zlib. Reopening and BLAKE3-hashing those nine cost 16,176,022 guest instructions in each read order. The stronger finite held input set also includes the selected serde_derive DSO and the observer's own runtime. It passed ordinary native controls on our controlled host. Valgrind added an unregistered executable, so the stronger policy refused that installation. The two three-file timings above do not price the entire stronger policy. The stock installation's root-owned system files and a custom preload take the ordinary compiler path. A separate native-hardware registration uses the published -24 compiler.

To verify all original guest positions and native bodies offline from this checkout, use Python 3.11+, GNU ar and zstd. The destination directory must be new, with at least 300 MiB available.

```sh
sha256sum -c scripts/ron-existing-rlib-evidence/SHA256SUMS
python3 -IB scripts/ron-existing-rlib-evidence/verify.py /tmp/ron-guest-evidence
```

The archive contains every raw native compiler and supervisor Callgrind file, per-phase argv, original status/registration, rlib, rmeta and dep-info. The reader derives each count from exclusive position records and checks both processes' full commands, native selection, archives and typed metadata. The compressed original archive SHA-256 is `374bb429ca5b084af3eb4d3c72e59e90217158fb39a42df3b4688bbfee7ba323`.

[Original signed Ron source inputs and native replay](../ron-consumed-metadata/README.md) · [Module search and authentic proc-macro controls](../ron-module-resolution/README.md) · [Separate released -24 ordinary Cargo and complete runtime pricing](../ron-ordinary-backend/README.md)
