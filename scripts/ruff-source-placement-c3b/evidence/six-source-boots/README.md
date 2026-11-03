# Whole-Cargo user instructions on six independent Linux boots

The guarded source-placement compiler reduced the Ruff #28106 settings build from **112.084 billion to 81.596 billion retired user instructions**, a median reduction of **27.194%**. The earlier compiler used 92.807 billion, a 17.202% reduction against the same baseline. All six boots cleared the preregistered 10% threshold for both candidates. None reached 2×. On the held-out Ruff #27836 edit, building the `ty_server` e2e test took **3.698% more instructions** with the guarded compiler. Cold builds took 4.691% more instructions for the settings library and 5.942% more for e2e. [Study registration and operators](https://github.com/astral-experiments/ohm/tree/ece4528e7e0e2d35a8fb4072fcb54ec7a245f5a8/scripts/ruff-source-placement-c3b) · [Six acquisitions, six independent raw readers and aggregate](https://github.com/astral-experiments/ohm/actions/runs/41501796384)

| Historical workflow | Baseline #337, billions | First prototype C2, billions | Guarded prototype C3b, billions | Paired reduction, baseline to C3b |
| --- | ---: | ---: | ---: | ---: |
| Settings cold build | 1,803.044 | 1,884.222 | 1,887.593 | −4.691% |
| Settings edit | 112.084 | 92.807 | 81.596 | +27.194% |
| Settings unchanged | 0.485 | 0.485 | 0.485 | +0.009% |
| e2e cold test build | 2,151.665 | 2,274.022 | 2,279.539 | −5.942% |
| e2e edit | 31.209 | 32.306 | 32.356 | −3.698% |
| e2e unchanged | 3.356 | 3.357 | 3.356 | +0.012% |

The settings edit saved an additional 12.068% versus C2. The baseline-to-C3b median interval was 27.180%–27.223% for this edit and −3.766% to −3.583% for the e2e edit. Both unchanged intervals included zero. Each individual two-sided interval uses the six observed paired extrema and has 96.875% coverage under independent, continuous boot differences. Together the two baseline-to-candidate primary intervals have at least 93.75% coverage. The exact one-sided global sharp-null test was 8/720. Conditioning on the position of the third compiler left eight allowed orderings per pairwise comparison. Each primary pairwise tail was 1/8, its best attainable value. [Every raw count, interval, allocation and memory figure](reviewed-tables.md)

After the settings edit, median target plus shared-directory allocation was 1,600,757,760 bytes for #337, 1,606,619,136 for C2 and 1,606,596,608 for C3b. The e2e edit left 2,343,749,632, 2,350,895,104 and 2,350,868,480 bytes, respectively. The largest individual descendant's median peak RSS on the settings edit was 842,808, 933,566 and 916,960 KiB. For e2e it was 730,752, 758,008 and 753,434 KiB. The complete per-phase census counted unique filesystem allocation across both roots and includes the optional records in `work-products.bin`. [Per-boot data and methodology](protocol.json)

## Native behavior and sources

The settings edit invoked one real `ruff_workspace` compiler. Its unchanged repeat invoked zero compilers. The e2e edit invoked the real `ty_server` and e2e compilers and one stock Wild. The unchanged e2e repeat still invoked one link-only compiler and one Wild. All roles agreed on the complete native reader and the corresponding independently clean executable. The e2e inventory changed from 151 to 152 tests. A deliberately contrary executable reported the expected failure. Each ordinary history reported E0308 on invalid source and reproduced independently clean bytes after repair.

C3b physically published 15 of 21 dirty settings objects on the forward edit and 14 on the return. The original, edited, independently empty and return references checked all 125 ordinary owner objects. Corrupting one eligible prior object forced that unit through ordinary LLVM and left 14 successful placements. Corrupting the optional index forced all 21 through ordinary LLVM. All resulting native objects matched the independent reference. [Original native proofs, including both adverse inputs](native/README.md)

The exact compiler sources were `531eb1980c08c75ccbf3f6b77adbee53cd9b8bd5` (#337), `4e546b27c311f29d99f9528e64420887f57c7538` (C2) and `ed0262f9bdc384576925229764971f23a141c95f` (C3b). Every scored boot used all three source-built compilers with matched Cargo, LLVM and Wild. The six boots used each possible compiler order once. The hardware counter inherited every thread and child from the actual Cargo process and required equal enabled and running time. No wall-time estimate was enrolled.

The earlier two-pair C2 screen missed its original 2× requirement. The separate Ruff #28277 documentation edit in Rust draft #340 used its own source and six pairs and reduced whole-Cargo instructions by 9.52%, with the expected native GDB location and test behavior. That experiment contributed zero observations to this packet. The later Stock4 compiler likewise has its own registration and acquisition. [Original two-pair screen](https://github.com/astral-experiments/ohm/blob/01b81575b92dfb7bfc8f8a2fdf43329486d75ba6/scripts/ruff-source-placement/evidence/c2-cargo-two-pair/README.md) · [Independent #28277 result](https://github.com/astral-experiments/ohm/blob/787c9b8f726153700a51ebb2a2bbcc2fe7db1f6d/scripts/ruff-callable-placement/attempts/41484772820/README.md)

## Offline verification

From this directory, run

```sh
sha256sum --check --strict --quiet SHA256SUMS
python3 -IB test_observations.py
python3 -IB review_summary.py
python3 -IB native/verify.py
```

`receipts.json` binds the original GitHub job and archive identities. The six independent readers each downloaded their source-matched raw archive. The six archives totaled 1,784,701,263 bytes. The six original compact reader ZIPs, aggregate and two native admissions are included here. The offline verifier reconstructs the bytes of all 108 hardware-counter records and their SHA-256 digests, recomputes the complete order randomization, checks native and resource records, and rejects seven changes to genuine observations.
