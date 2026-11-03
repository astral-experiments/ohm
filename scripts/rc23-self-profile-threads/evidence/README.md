# Stock Rust 1.99 reproduces the parallel instruction-profiler assertion

Official rustc 1.99.0, commit `b940084d7eb6a299eb4bfeb8e34901bc051e7ac4`, aborted in an LLVM worker when compiling a 32-codegen-unit library with `-Zself-profile-counter=instructions:u`. The same first assertion reproduced on the source-built #329 compiler. This classifies the reduced failure as an upstream profiler limitation. The three repetitions per cell do not estimate failure rates.

| Native build, by compiler | Ordinary, 1 / 8 frontend threads | Wall profiler, 1 / 8 | Instruction profiler, 1 thread | Instruction profiler, 8 threads |
| --- | --- | --- | --- | --- |
| Official Rust 1.99.0 | pass / pass | pass / pass | 3 passed | 2 passed, 1 SIGABRT |
| Signed Ohm -23 | pass / pass | pass / pass | 3 passed | 3 passed |
| Ohm #329 source-built | pass / pass | pass / pass | 3 passed | 2 passed, 1 exit 101 |

The first failing frame on stock was the drop of `rustc_data_structures::profiling::TimingGuard` inside `rustc_codegen_llvm::back::write::codegen`. On #329 it was the guard drop inside `…::write::optimize`. Both ran in a named `opt` worker and failed the same `start <= end` assertion in `measureme-12.0.3/src/raw_event.rs:55`. The original separate Ruff #29697 diagnostic failed in `optimize` and aborted during unwinding. Its ordinary edit and unchanged controls are independently archived. [Original Ruff stderr and inputs](https://github.com/astral-experiments/ohm/tree/aef2e7ebdd8dd109b755bfea76ea9aa70ec381a2/scripts/ruff-original-ty-instructions/standalone-buckets/residual/eligibility/evidence-41671764437)

All three source trees use the same checksummed measureme 12.0.3 and the same Rust self-profiler implementation. measureme opens a userspace hardware event for the creating Linux thread, keeps a physical counter-register index and measures differences using RDPMC. Rust shares that profiler with codegen workers. The measurement library documents its hardware counters as single-threaded. The captured panic proves a backwards event interval. The individual register readings and CPU migration history at that instant were unavailable. A successful multi-threaded profile does not validate its instruction counts. [Source bindings](source-bindings.json) · [measureme counter documentation and implementation](https://docs.rs/measureme/12.0.3/src/measureme/counters.rs.html)

One Linux x86-64 worker ran 39 fresh fixture compiles on the same boot. Both thread settings kept 32 codegen units and O1. Only stock used crate-scoped `RUSTC_BOOTSTRAP=counter_fixture`. All nine metadata-only controls passed. Each of the 28 successful native builds emitted 32 objects, linked an independent consumer and returned both expected arithmetic values. Every one of 27 allocated file-backed ELF sections matched within its compiler except the GNU build ID. Full executable and library hashes differed across the isolated output directories. The fixture preserves its raw sources, stream table and every stderr. [Native worker](https://github.com/astral-experiments/ohm/actions/runs/41675571979/job/126055149424) · [Source and controls](../registration.json)

The first acquisition stopped before any fixture compile because its receiver required a GNU build ID on the official BOLT driver. The official 1.99.0 image has SystemTap and BOLT notes only. The successor pins its complete file hashes and exact absence of a build ID. Both Ohm images retain their expected GNU IDs. The registered crate, flags, cases and acceptance rule are identical. [Preserved acquisition refusal](https://github.com/astral-experiments/ohm/actions/runs/41675070338)

To reopen the permanent compact records, run the first command from this directory. The full original upload (25,301,874 bytes, SHA-256 `e6dc7a3c0cf8821a84c698a630deab1a2924663e988efdddb11420916e30c758`) additionally retains the ELF, archive and event bodies.

```sh
python3 -IB verify.py
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13249294700/zip > /tmp/rustc-self-profile-41675571979.zip
python3 -IB verify.py /tmp/rustc-self-profile-41675571979.zip
python3 -IB reopen.py /tmp/rustc-self-profile-41675571979.zip e6dc7a3c0cf8821a84c698a630deab1a2924663e988efdddb11420916e30c758 .. /tmp
```
