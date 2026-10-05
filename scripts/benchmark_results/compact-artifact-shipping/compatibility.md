# Automatic compact storage and ordinary consumers

This revision separates the choice to store compact objects from the choice of
linker. Cargo enables compact storage with Ohm defaults on supported native
x86-64 GNU Linux toolchains. The bundled Wild reads compact objects directly;
rustc reconstructs private ordinary inputs for other consumers.

Native compatibility validation and all 90 timing commands pass. The
[measured tradeoff](compatibility-results.md) supports automatic storage with
bundled Wild, while retaining the explicit opt-out and documenting the larger
custom-linker cost. The previous candidate's 156-command and
416-command datasets remain separate; they do not prove this revision's
behavior or performance.

The native compatibility and timing cut uses Rust source patch `4790daed` and
Cargo source patch `20b9d1fd`, with Wild unchanged at `9179eb98`. The published
Cargo follow-up also restores the inactive feature path's existing configuration
discovery, corrects test assertions and wrappers, and extends CI selection.
Independent review of all 90 recorded commands confirms that the production
guard does not return early in any benchmark configuration:
ordinary storage selects Wild, while the default and adapter arms select compact
storage. The timings still identify the frozen build; they do not claim the
rebuilt final Cargo binary has identical performance.

## Configuration behavior

| Configuration                                                       | Behavior                                                                               |
| ------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Native x86-64 GNU Linux, matching v2 toolchain                      | Compact storage automatically; bundled Wild reads it directly.                         |
| `-Zohm-compact-artifacts=no`                                        | Ordinary storage; other Ohm defaults remain enabled.                                   |
| `-Zohm-defaults=no`                                                 | Ordinary storage unless compact storage is explicitly requested.                       |
| Older toolchain or another host/target                              | Automatic selection uses ordinary artifacts.                                           |
| Explicit linker in configuration, profile, command, or build script | Preserve that selection; materialize ordinary link inputs when necessary.              |
| Thin or fat LTO                                                     | Extract bitcode from compact dependencies, including for ordinary consumers.           |
| Linker-plugin LTO                                                   | Keep raw bitcode and the selected linker; it must support the producer's LLVM version. |
| Packed split DWARF                                                  | Materialize private ordinary inputs for debug packaging.                               |
| Unpacked single-file DWARF                                          | Retain an ordinary debugger object while preserving compact cache inodes.              |
| Explicit metadata/format override or opaque rustc response file     | Automatic compact storage yields to the supplied configuration.                        |

Explicit `-Zohm-compact-artifacts=yes` reports unsupported targets, missing v2
capability, and conflicting or opaque storage settings. These checks apply to
an explicit request; automatic enablement preserves those builds with ordinary
storage.

The `compact-artifacts-v2` marker promises the expanded compiler consumer
support. The object encoding remains `RCOBJ001`; this is an interface revision,
not a second object format. Both storage and direct-linker capability are
tracked compiler options. Cargo includes its generated choices and user
configuration in fingerprints and removes only its own recorded driver
arguments when a late linker choice arrives.

## Correctness and safety

Private ordinary inputs live until native linking and debug packaging finish.
Original local output paths are restored before normal cleanup, and replay
recipes retain original paths. Archive construction preserves member selection
and basenames. Retained debug objects are replaced atomically, without changing
shared incremental inodes. There is no external object store or separate
garbage collector.

The shared decoder is unchanged at Wild `9179eb98`. Its prior integrity and
length checks remain applicable; they do not establish an aggregate process
memory bound or substitute for hostile-input fuzzing.

The source review found no remaining correctness or safety blocker in these
adapters. Local compiler formatting, tidy, and macOS compiler typechecking pass.
All three forced native
run-make suites pass with one test executed and none ignored in each suite.
The supplementary native checks cover direct Wild with packed/unpacked and
split/single DWARF, GDB source and argument lookup, ordinary BFD replay, and an
actual linker-plugin LTO executable through LLVM 23 LLD. The previous compiler's
packed-DWARF and plugin-LTO rejections are retained as before/after evidence.

Cargo's local focused selection, argument-range, cache-admission, help, and
macOS fallback checks pass. Review corrected a wrapper argument-index defect,
opaque-response-file precedence, and missing `off`/`n` metadata boolean aliases.
Native Linux validation found and fixed a freshness bug: an explicit compact
request could otherwise reuse an ordinary fallback build without diagnosing
its conflicting options. Validation now runs before cache reuse. The original
failing execution and the passing regression remain in the evidence.

All 12 required focused Linux Cargo tests and all 32 installed-toolchain policy
checks pass. The latter exercise actual executable, library, proc-macro and
doctest behavior, configuration and late linker choices, mode switching, old
marker fallback, metadata/response overrides, Thin/Fat LTO, packed DWARF, and
cleanup. Transparent wrappers record compiler arguments in this policy suite;
unwrapped whole-project performance and cache behavior are measured separately.

A pre-existing dylib test expected the absence of an explicit metadata flag
that the implementation deliberately emits. The base and candidate both build
and run its native behavior correctly. We correct that stale assertion while
preserving its separate-metadata check, and force this previously ignored test
in CI. The corrected test passes locally, in both platform CI jobs, and in the
final native rerun with the new compiler.

The first full Cargo CI run additionally found stable-test forwarding of
Ohm-only replay options and two ordinary-build diagnostic regressions from
unnecessary configuration reads. The follow-up filters those options only in
the test helper and restores the inactive production path before configuration
discovery. The existing diagnostic assertions remain unchanged. All eight
enabled CI jobs pass at Cargo `76793c44`, including both platform integration
suites and actual execution of the six Linux linker-policy tests. The compiler
PR pins this commit at Rust `b0e3800d`. Its three GitHub jobs stop at the known
missing private-source App client ID, before compiler checks; local proof is
reported separately.

The separate final Cargo `76793c44` native build passes all 15 selected tests:
selection, recorded-argument provenance, wrappers, all six linker-policy tests,
the corrected dylib case, and the two unchanged ordinary-build diagnostics.
Five installed-Cargo runtime cases also pass, covering automatic compact
storage, its explicit opt-out, disabled Ohm defaults, opaque-response fallback,
and the LLD adapter. This build uses a separate install and target; the measured
Cargo/compiler binaries remain unchanged. This establishes final-build
functionality without attributing the frozen timing results to a rebuilt binary.

## Timing scope

The confirmation compares ordinary storage and automatic compact storage with
the same compiler, Cargo and Wild binaries. It runs two fresh forward/reverse
rounds on Ruff and uv, each with a clean build, initial no-op, three sequential
application-function edits, three sequential library-function edits, and a
final no-op. A third Ruff arm explicitly selects the same Wild through user
configuration, exercising ordinary-input materialization. That arm includes
all effects of the custom configuration, including cache admission; it does
not isolate decoder cost.

The total is 90 commands: 54 Ruff and 36 uv. Each runtime oracle checks the
edited behavior. Results retain absolute and relative wall-time differences,
paired medians and ranges, per-round values, CPU time, settled allocation, and
sampled process-tree RSS. Three edits within one round are sequential samples,
not independent fresh builds. Allocation covers the private target, shared
build subtree and scratch lane with hardlinks counted once; it is neither peak
temporary disk usage nor unique physical CoW allocation.

The compiler is a non-PGO/BOLT development build, using eight Cargo jobs and
development profiles on one Linux host. This confirmation measures the cost
of enabling storage compression within the new compiler. The previous studies
retain the separate pristine-compiler comparison. Neither comparison proves
constant overhead, the frequency of edit types, or production-release timing.

## Reproducible evidence

The [performance archive](measurements/compatibility/README.md) contains all 90
commands, runtime/resource logs, fixture originals, source and binary identities,
the frozen verifier, and independent paired arithmetic. A fresh extraction
reproduces the recorded summary and independent calculation exactly. The original
postprocessing failure is retained: Cargo's verbose logs include multiline
commands and build-script `RUSTC` environment values, which the first parser
mistook for compiler execution. The corrected parser validates actual executed
commands, including all 20 no-ops. No raw timing row was changed or excluded.

The [correctness archive](correctness/compatibility/README.md) carries source
reviews, native logs, CI results, current source bindings, and the final Cargo
validation separately. These portable checks verify recorded evidence; they do
not rebuild compilers or rerun the benchmark. Both layers are independent of the
earlier study archives and must be extracted into separate fresh directories.
