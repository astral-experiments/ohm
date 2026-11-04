# Ruff Unicode normalization dependency update

The six fresh boots measured **28.294% fewer retired instructions** at the paired median for the edited unicode-normalization rustc. The complete `cargo +ohm check -p ruff_python_parser --lib --locked --offline` used **2.754% fewer instructions**. The ordinary edited build saved 0.835%, a separate descriptive endpoint.

Both pilots cleared the 20% compiler threshold and improved the complete command. All six fresh pairs improved on both endpoints, and the compiler median cleared 20%. C5 is source-built Rust 6c2874a0b6a0bf3570f8959733b6f87907e5cce6. C7 is its direct child 06fe634feaa39288210a6f17b8994346a5fae1c1. Both used the same released Linux Cargo and Wild and the same developer profile on historical Ruff #21229, a lockfile-only update from unicode-normalization 0.1.24 to 0.1.25. The primary counted the physically identified compiler and its threads from exec to exit. The whole-check value came from a separate, untraced invocation on the same history. [Registration](../registration.json) · [Source and software-counter admissions](../software-admission.json) · [C5 factory](https://github.com/astral-experiments/ohm/actions/runs/41738460962) · [C7 factory](https://github.com/astral-experiments/ohm/actions/runs/41753724558)

## Six fresh paired blocks

| Boot | Order | C5 rustc | C7 rustc | Saved | C5 whole check | C7 whole check | Saved |
|---|---|---:|---:|---:|---:|---:|---:|
| B1 | C7 → C5 | 2,486,415,287 | 1,782,734,334 | 28.301% | 25,427,462,276 | 24,727,805,800 | 2.752% |
| B2 | C5 → C7 | 2,484,783,015 | 1,782,738,327 | 28.254% | 25,427,245,628 | 24,721,099,018 | 2.777% |
| B3 | C5 → C7 | 2,485,237,556 | 1,781,905,628 | 28.300% | 25,426,223,726 | 24,725,485,779 | 2.756% |
| B4 | C7 → C5 | 2,486,284,939 | 1,781,719,532 | 28.338% | 25,427,503,780 | 24,728,331,244 | 2.750% |
| B5 | C5 → C7 | 2,485,210,142 | 1,782,355,613 | 28.281% | 25,424,300,816 | 24,732,651,154 | 2.720% |
| B6 | C7 → C5 | 2,485,116,982 | 1,782,114,865 | 28.288% | 25,429,388,958 | 24,726,279,068 | 2.765% |

6 of six paired compiler differences favored C7. The two-sided exact sign test yields p=0.03125 for the registered primary (one-sided 1/64 for six favorable pairs). The whole-check differences had the same six signs. The two pilot reductions of 28.266%, 28.309% on the owner and 2.764%, 2.769% on the whole check were excluded from confirmation. [Six raw-derived projections](confirmation/qualified.json) · [Second independent compiler and whole-command counter reader](independent_counter.py) · [Two pilot projections](pilot/qualified.json) · [Confirmation run](https://github.com/astral-experiments/ohm/actions/runs/41756899118) · [Pilot run](https://github.com/astral-experiments/ohm/actions/runs/41755609477)

## Other ordinary commands

Counts are role medians across the six fresh boots. Savings are paired medians and observed ranges. A negative value means the candidate used more instructions.

| Scope | C5 | C7 | Savings | Range |
|---|---:|---:|---:|---:|
| Cold check, old lock | 182,400,441,800 | 180,866,736,294 | 0.843% | 0.835% to 0.848% |
| Empty check, edited lock | 182,404,029,542 | 180,875,265,944 | 0.837% | 0.827% to 0.851% |
| First unchanged check | 208,747,962 | 208,760,920 | -0.007% | -0.020% to 0.007% |
| Unicode compiler, empty edited check | 2,484,097,072 | 1,780,219,133 | 28.336% | 28.332% to 28.351% |
| Cold build, old lock | 273,064,498,137 | 271,541,060,558 | 0.557% | 0.545% to 0.570% |
| Whole edited build | 84,450,717,572 | 83,742,191,909 | 0.835% | 0.815% to 0.863% |
| First unchanged build | 210,347,086 | 210,301,296 | 0.010% | -0.064% to 0.042% |
| Empty build, edited lock | 273,072,425,148 | 271,553,782,144 | 0.557% | 0.545% to 0.571% |

The common cold/settled guard required both a 2% increase and ten million additional instructions to refuse. Individual absolute counters and all ordinary repairs are in the projections.

## Inputs and native verdicts

* Each role produced 96 typed units from empty, four real rustc processes on the edit, and zero non-fresh Cargo products on its first repeat. Every physically extracted registry source file matched its archive from the 506-member union of the original locks. At the selected compiler, Cargo supplied its own compiler-specific registry directory in the output directory, two search paths and tinyvec extern. The remaining literal argv matched. [All four compiler lifetimes and actual argument differences](confirmation/attribution.json)
* A private 512-element tuple array appended to the checked-out Ruff parser reported the same five-byte u16 overflow twice in each of check and build, at byte range 27635–27640. Each compiler's full edited, unchanged, repaired and independently empty native observer images matched. The native reader exercised 1,112,064 Unicode scalar values and six real parser expressions. Only U+A7F1 gained NFKC result S. The two compilers produced distinct observer ELFs, including differing .text. All cross-compiler checks of the original complete stdout passed.
* For the edited registry crate on these hosts, check .rmeta changed from 1,455,967 to 469,100 bytes and build .rmeta from 1,701,059 to 714,187 bytes. The .rlib was 209,076 bytes in both. All registry products matched their own independently empty counterparts. The downstream Ruff parser's raw .rmeta and .rlib can differ on warm versus empty builds. Independent signed, C5 and C7 decoding found the same ten differing lines including seven upstream crate hashes. [Target layouts, cross-compiler native checks and metadata interpretation](https://github.com/astral-experiments/ohm/blob/7856f60de130e8cdd87f797394e3463bbfc68cbe/scripts/ruff-normalization-price/evidence/target-layout/README.md)

## Restore the official ZIPs and verify the results

One compressed pilot ZIP and seven zstd dictionary patches preserve all 247,570,461 original GitHub bytes in 64,051,064 bytes of transport, including the official metadata. The reader verifies each official size and SHA, hashes the genuine libraries and metadata, reopens all exec-stop journals and hardware counters, reads both original invalid attempts, and executes every distinct native ELF on Linux x86-64. [Archive anchor](raw/anchor.json) · [Genuine raw-record corruption controls](pilot/independent-corruptions.json)

~~~sh
suite=scripts/ruff-normalization-price
out=$(mktemp -d)
for cohort in pilot confirmation; do
  if [ "$cohort" = pilot ]; then
    head=85ebd805db21f99dee180de98524ddb28a53e5d6
  else
    head=ff996ed2c6c7db5d739f3c92b8ed90aa68db4f37
  fi
  python3 -IB "$suite/evidence/zip_store.py" restore "$suite/evidence/raw" "$cohort" "$out/$cohort"
  python3 -IB "$suite/review.py" "$cohort" "$out/$cohort" --head "$head" --out "$out/$cohort/verified.json"
  cmp "$out/$cohort/verified.json" "$suite/evidence/$cohort/qualified.json"
  python3 -IB "$suite/evidence/attribution.py" "$out/$cohort" "$out/$cohort/verified.json" "$out/$cohort/owners.json"
  cmp "$out/$cohort/owners.json" "$suite/evidence/$cohort/attribution.json"
  python3 -ISB "$suite/evidence/independent_counter.py" "$out/$cohort" "$out/$cohort/verified.json" "$out/$cohort/independent.json"
  cmp "$out/$cohort/independent.json" "$suite/evidence/$cohort/independent_counter.json"
done
~~~
