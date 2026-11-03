# Ruff library builds with source-owned codegen partitions

The compiler used spare capacity under the 256-unit limit to split the unsplit crate root and volatile root by a stable local callable owner. The two compilers share the original source-matched Ohm −23 port of Rust #329, which recovers codegen units after unrelated upstream instantiations change. The experiment changes the partitioner at normal optimization level 1. Both compilers use the same Cargo, std, LLVM configuration, Ruff source and target arguments. The source constructor includes the exact compiler commits and a verified Git bundle. [Compiler source](https://github.com/astral-experiments/ohm/tree/df534d61d22a8876e13f57f6033f2f11768a4a60/scripts/ruff-matched-stage) · [Original selection over all 245 units](https://github.com/astral-experiments/ohm/tree/815b9a427ba70fd1233bc52556fd3ddedc6651e6/scripts/ruff-original-ty-instructions/standalone-buckets/residual/eligibility/evidence-ordinary-partitions)

## Ruff #29697

One x86_64 Linux host measured inherited retired user instructions for the complete normal command, in parent then candidate order.

~~~sh
cargo +ohm build -p ty_ide --lib --locked --offline -j4 --message-format=json
~~~

| Phase | Parent | Candidate | Change |
| --- | ---: | ---: | ---: |
| Empty OLD build | 2,098,224,281,073 | 2,099,286,063,530 | +0.05% |
| Actual upstream edit | 19,057,505,352 | 19,741,833,873 | +3.59% |
| First unchanged NEW | 423,083,419 | 423,183,955 | +0.02% |
| Independent empty NEW | 2,097,739,821,866 | 2,099,891,007,566 | +0.10% |

Both compilers ran ty_project and ty_ide on the edit. Both retained exactly 241 earlier ty_project objects. The parent regenerated two changed objects and two byte-identical objects. The candidate regenerated seven changed objects and three byte-identical objects. The combined size of changed objects grew from 1,384,064 to 1,386,664 bytes. All 171 parent and 183 candidate ty_ide objects were retained.

A separate worker decoded both entire compiler query caches, checked the complete codegen vector against the actual archive members and recovered all eight split units. The actual emitted ty_project units contained 2,336 → 2,873 item memberships and 26,027 → 31,982 compiler MIR size units. The extra 537 memberships and 5,955 size units also equal the increase over the entire crate. The change duplicated inline work across the new units. The edited target contained 5,120 → 5,220 physical files and used 2,226,425,856 → 2,225,770,496 allocated bytes.

Both archives passed ranlib and full native-member verification. The separately executed OLD client produced the OLD dependency behavior. The edited, repaired and independently clean clients agreed in each role. Invalid Rust returned E0308 in both. This single-hardware comparison and structural result do not establish a population estimate. [Ordinary run](https://github.com/astral-experiments/ohm/actions/runs/41706721214) · [Independent native reader](https://github.com/astral-experiments/ohm/actions/runs/41708694898)

The first process observer recorded positive instructions without a valid enabled/running clock for some intervals. The later ordinary worker uploaded the complete normal pair before a Python import failure in its optional observer. Both cases are excluded from per-compiler pricing. The whole-command counter uses a separate inherited event with exact enabled/running agreement.

The file 29697-controls.zip contains original unmodified phase records, actual Cargo output including the invalid edit, frame digests and the complete native inventories. Its manifest binds each saved entry to the 400,903,442-byte original artifact 13266000990 with SHA-256 9a1b4cffbe9c717b920c52fb3b57e6c82a7cad761ded3da6a15cad73fca209e2. The file 29697-native.json contains the separate audit of both complete native histories, including physical compiler and native caller results. The original archive retains the actual native bytes.

The existing Ohm #183 heuristic handles much larger CGUs. The measured roots had final-size estimates 11,243 and 9,746, below its threshold of 32,768. Current Ohm #59 also contributes initial ownership information for upstream generics. The new layout did not improve this edit. [Existing split rule](https://github.com/astral-experiments/ohm-rust/pull/183) · [Existing caller ownership](https://github.com/astral-experiments/ohm-rust/pull/59)

## Ruff #29604

This independently selected body-only edit ran candidate then parent. OLD cancelled an outstanding Salsa snapshot on an unrelated .log change. NEW allowed it to complete. An empty action and an explicit cancel tested both sides of that observation. The same client called the emitted ty_ide vendored-path API, and the two compilers passed OLD, edited NEW, repaired NEW and independently clean NEW. The initial one-change public revision counter failed to distinguish OLD and NEW and was rejected before an edited command. The original source change, true cancellation observable, strengthened harness and first refusal are in the [held-out run](https://github.com/astral-experiments/ohm/actions/runs/41708694898).

| Phase | Parent | Candidate | Change |
| --- | ---: | ---: | ---: |
| Empty OLD | 2,063,147,623,728 | 2,064,114,528,294 | +0.05% |
| Old → edited NEW | 23,124,975,972 | 23,646,147,999 | +2.25% |
| First unchanged NEW | 419,591,883 | 419,362,845 | -0.05% |
| Independent empty NEW | 2,063,054,351,709 | 2,064,835,753,717 | +0.09% |

Parent and candidate both retained 241 earlier ty_project CGUs. The parent regenerated four changed objects and one equal object. The candidate regenerated eight changed and three equal. The physical partition charged 4,172 → 4,658 mono memberships and 39,216 → 44,219 MIR size units to the recompiled objects. New/parent allocated disk for the edited targets was 2,196,852,736 / 2,195,935,232 bytes, with 5,171 / 5,069 physical files. These are one-host resource controls.

## Individual compiler processes

A separate task-scoped counter opened on each real stopped rustc exec and inherited only threads of that process through exit. All accepted lifetime events had equal enabled and running clocks. The calibration directly exercised threads and a separate fork/exec. For #29697 the complete diagnostic ran on its own host and reproduced the two actual native archives and the different OLD/NEW program outputs from the ordinary packet. For #29604 the diagnostic ran outside the ordinary windows on the same machine. [Original diagnostic](https://github.com/astral-experiments/ohm/actions/runs/41709576028) · [Independent verification of all four original packets](https://github.com/astral-experiments/ohm/actions/runs/41711197630)

| Case | Process | Parent instructions | Candidate instructions | Change |
| --- | --- | ---: | ---: | ---: |
| #29697 | ty_project | 14,339,143,097 | 15,017,121,211 | +4.73% |
| #29697 | ty_ide | 4,226,904,838 | 4,234,548,121 | +0.18% |
| #29604 | ty_project | 18,821,768,632 | 19,368,722,909 | +2.91% |
| #29604 | ty_ide | 3,900,392,718 | 3,902,070,559 | +0.04% |

The source-owned lanes increased whole-command and affected-compiler work for both prospective edits. We stopped this policy after these two pilots. Each case has one ordinary paired host, so the reported percentages describe these runs.

### Replay

On x86_64 Linux with Python 3.11+, binutils and zstd, set GH_TOKEN to a read-only token for these four Ohm workflow artifacts, set RUNNER_TEMP to an empty writable directory, then run the following from this source checkout. The reader enforces an 8 GiB available memory and 15 GiB disk reserve, downloads the exact four originals from the manifest, verifies their full SHAs, and emits both independent native and retired-instruction readbacks. The small control and lifetime archives in this directory preserve the ordinary phase ledgers and original kernel events after the full hosted native archives expire.

~~~sh
python3 -IB scripts/ruff-original-ty-instructions/standalone-buckets/owner-lanes/evidence-two-edits/review_originals.py
~~~
