# Profiling Ruff's CLI help edit on released Ohm -24

Changing one help example costs **1.884 billion retired user instructions for cargo check and 17.38 billion for cargo build** on the signed Linux x86_64 release. One ordinary Ruff library module costs **9.03 billion** during codegen. Its 125 functions have the same names, sizes, placement and resolved relocations before and after the edit. Two generated Clap methods each change one instruction. The separate version module also has a genuine observable change.

This is a stock measurement for selecting a compiler experiment. The two builds used the same released compiler. [Genuine Ruff change](https://github.com/astral-sh/ruff/pull/28392) · [Signed release](https://github.com/astral-experiments/ohm/releases/tag/1.99.0-24) · [Ordinary check worker](https://github.com/astral-experiments/ohm/actions/runs/41718614781) · [Ordinary build and unthrottled attribution](https://github.com/astral-experiments/ohm/actions/runs/41722911354)

## Complete Cargo commands

The worker checks out f3280423f6c535690287e8169c25929f8d6433ce, runs the actual Cargo command, and checks out d136bd8d002a648de5f344df602e492658306f1e at the same path. Cargo.lock is identical. These are the entire commands. The environment fixes four Cargo jobs and disables network access for Cargo after prefetch. Each worker owns its Cargo home and both output directories.

    cargo +ohm check -p ruff --bin ruff
    cargo +ohm build -p ruff --bin ruff

| Ordinary endpoint | First independent worker | Second independent worker | Unchanged after edit |
| --- | ---: | ---: | ---: |
| cargo check | 1,884,557,042 | 1,884,234,586 | ~480 million, zero rustcs |
| cargo build | 17,382,486,167 | 17,379,699,633 | ~508 million, zero rustcs and linkers |

Fully cold check took about 781 billion instructions. Fully cold build took about 2.05 trillion. Both edited commands ran the actual ruff library and binary compilers. On a separately recorded ordinary build re-edit, the inherited counter measured 17,375,687,303 instructions. Kernel lifetime events measured 13,804,665,180 in the library rustc, 215,006,862 in the binary rustc, 2,811,263,842 in Wild's fork worker and 519,166,175 in Cargo. The counter includes the whole child tree and excludes the kernel. The linker starts under the ld.bfd spelling. Its executable mapping is the signed Ohm Wild binary. [Counter source](../whole_count.c) · [Kernel task counter](../exec_count.c) · [Raw constituent totals](readback/final-build.json)

Actual top-level, check and format help all show the exact five-byte change. The old executable still prints the old example after the source edit. Both new and independently cold executables lint an F401 and reject the old invalid config. The edit's complete 147,223,880-byte CLI ELF equals the independent cold NEW. The two retained executables also report the exact respective OLD and NEW commit IDs through the real JSON version subcommand. A source error reports E0308 on two successive checks, the repair succeeds, and the unchanged command skips both compilers. [Complete ordinary build outputs](readback/final-ordinary-build.json) · [Check outputs](readback/ordinary-check.json) · [Version verdicts on the original bodies](readback/real-version-verdicts.json)

## What actually ran in rustc

232 of 236 library codegen units retained the previous object device, inode, mtime, size and SHA-256. All 20 binary objects were retained. Four library LLVM workers really optimized. The source queues Optimize and CopyPostLtoArtifacts with distinct thread names. The kernel records each thread name with the owner PID and TID. All CGU prefixes joined uniquely to the actual members, and every observed child task had a nonmultiplexed counter. The following counts come from two independent hosted processes. [Signed worker scheduling source](https://github.com/astral-experiments/ohm-rust/blob/f5a51d8cc3e76236c2d0f17d495d59ebb03306e4/compiler/rustc_codegen_ssa/src/back/write.rs) · [First direct task counts](readback/first-build.json) · [Second direct task counts](readback/final-build.json)

| Emitted library CGU | Previous versus edited native output | First worker, billions | Second worker, billions |
| --- | --- | ---: | ---: |
| 26b50y1455r2nn7imncnrh1im | args, two actual instruction changes | 9.032 | 9.029 |
| 3u3vz84botgcprgohgbxpi18d | 204 functions, complete object identical | 1.053 | 1.053 |
| c3vf9hzmvyyz4hr2bieid2ks6 | 73 functions, complete object identical | 0.466 | 0.466 |
| 3xhp4sunmhbswr1ovpiqoyj96 | version, genuinely different code and commit ID | 0.080 | 0.080 |

The stable crate ID from the physically selected 236-object rustc session gives the exact ordinary module spelling ruff.6d12376b25bedff1-args. Its signed compiler CGU hash is 26b50y1455r2nn7imncnrh1im. The version module's native name likewise reproduces independently. The 1,644,904-byte args object is second by size among all 236. Reopening all four original objects and every actual allocation and resolved relocation establishes the following.

* The two changed functions are GlobalConfigArgs's augment_args and augment_args_for_update. Each changes the x86 instruction at offset 0x287 from mov $481,%edx to mov $476,%edx. The sole other changed allocated section is the help literal, also 481→476 bytes.
* The other 123 functions contain 316,775 byte-identical code bytes. All 125 full resolved relocation lists match. 95 function symbols are global definitions and 30 are local definitions in the emitted object.
* The seven Clap methods on GlobalConfigArgs have 9,748 bytes. The nine on CheckCommand have 133,149. The nine on FormatCommand have 53,781. None of those latter two groups' methods changed. The locked clap_derive 4.6.4 source emits the automatically_derived marker on both the Args and FromArgMatches trait impls. Its upstream crate SHA-256 is d012d2b9d65aca7f18f4d9878a045bc17899bba951561ba5ec3c2ba1eed9a061. [Original body and relocation comparison](readback/four-actual-objects.json) · [All 125 native methods and their receiver groups](readback/real-receiver-groups.json) · [Immediate instruction witnesses](readback/literal-instruction-witness.json) · [Clap source](https://docs.rs/crate/clap_derive/4.6.4/source/src/derives/args.rs)

A second recorder run with an 8,000,009-instruction period had zero lost events and zero PMU throttling. All 2,174 records match the raw kernel IP, TID, PID, time and period. Of 1,128 samples within the args worker, 1,066 landed in libLLVM. Spread across codegen passes, the samples support a coarse backend budget without assigning costs to individual source functions. The earlier 1,000,003-period build sample genuinely throttled 15 times. Its PC distribution is excluded. Its separately acquired lifetime task counters passed. An earlier perf launch changed the ambient Cargo environment and triggered a cold workload. Its numbers are excluded entirely.

On check, the large rustc took 1.263 billion instructions and the second took 114 million. Of 1,299 library-rustc samples, 227 landed in names associated with incremental queries or graph records, 166 in parser/AST/lowering functions, 123 in explicit hashing code and 116 in the loaded clap_derive image. These are direct leaf samples. The trace has incomplete stacks. [Raw kernel and symbolization receiver](read_samples.py)

## Native output and metadata controls

234 of the 236 library objects have the same complete bytes across the edit. All 236 library and 20 binary native objects in the edited build match independent empty NEW. All 3,741 library archive index symbol-to-member pairs agree. The linked CLI really changes code, data, relocation contents, unwind addresses and build ID across the edit. The changed runtime verdicts and independent equal binary are both required. [Native archive and ELF checks](read_ordinary.py) · [Full section changes from a separate boot](readback/final-ELF-differences-previous-boot.json)

The original inputs agree on 3,053 stable definition identities. OLD→EDIT changes 1,145/1,650 public item rows for check, and 1,351/1,671 for build. Across this edit, all required-dependency hashes agree. Warm NEW vs independently cold NEW has 30 differing dependency header hashes, as well as differences in local public rows, despite exact output executable and CGU equality. This evidence supports the native and CLI claims above. A raw rmeta equality claim would fail. [Check metadata](readback/check-metadata.json) · [Build metadata](readback/build-metadata.json)

## Boundary for a compiler experiment

A 20% reduction in the affected library rustc requires about 2.76 billion instructions. The two regenerated identical objects together account for only 1.52 billion. A 2× complete build would have to save 8.69 billion, or about 96% of the large args worker if all other costs stayed fixed. The function-size inventory supplies no per-function instruction price.

The existing compiler already finds trait methods' characteristic self DefId, maps it to the containing source module, and normally spends at most 256 slots. Its existing splitter requires a MIR estimate of at least 32,768 and has pre-internalization linkage and global-assembly guards. There are 20 unused slots in this build. A bounded placement experiment could keep roots of sizeable automatically derived trait impls for one local self type together, preserving all mandatory local copies and existing exclusions. The selector would rank genuine compiler MIR estimates across *every* source unit before looking at edit results. The exact original pre-internalization linkage, MIR-size ranking and reachable inline duplication still need qualification. [Existing partitioner](https://github.com/astral-experiments/ohm-rust/blob/f5a51d8cc3e76236c2d0f17d495d59ebb03306e4/compiler/rustc_monomorphize/src/partitioning.rs) · [Existing oversized-unit work](https://github.com/astral-experiments/ohm-rust/pull/183) · [Existing linkage guards](https://github.com/astral-experiments/ohm-rust/pull/185)

The independent edit selected before changing the compiler is Ruff #26372, 03f787e51e94999977b9a5a32b0153d82d7e2142 → fa4a7bca2db70229710892c97b26ea6fb046cfc4. It adds a real field and the observable --extend-exclude behavior to FormatCommand. Require its old/new CLI verdict, ordinary whole-Cargo counters, full native and clean functional comparison, two unchanged and invalid/repair controls, and cold storage/compile costs including any extra inline work. The earlier root/volatile lane proposal lost both of its prospectively selected edits. [Independent Ruff source and tests](https://github.com/astral-sh/ruff/pull/26372) · [Previous placement trial](https://github.com/astral-experiments/ohm/blob/ad933c47dce49d616cb2afba31f429ba7dff8961/scripts/ruff-original-ty-instructions/standalone-buckets/owner-lanes/evidence-two-edits/README.md)

## Reopen the results

From this directory on Linux with Python 3.11+, GNU c++filt and zstd available, run the following. The reader checks all six SHA-256 identities, reopens the original counter streams, matches the checksums of every carried object, independently decodes physical metadata and reruns the named-function comparison.

    python3 -IB verify.py

The compact ZIPs preserve original member bytes and an enclosing archive commitment. original-artifacts.json records original GitHub asset IDs, lengths and SHA-256 digests. The full native executables remain in the ordinary hosted originals. To rerun their command-level and JSON version checks, use read_ordinary.py and version_control.py on the corresponding full ordinary-build ZIP. The reviewed source includes the exact launchers, environment handoff and raw counter parsing. [Exact workflow source](https://github.com/astral-experiments/ohm/tree/1f6e6a7f22fe01ec3a645960d4c67686d2fd8d54/scripts/ruff-clap-config-help) · [All original artifacts](original-artifacts.json)
