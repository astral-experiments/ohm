# Two source-built Ruff workflow measurements

**Withhold the corrected writer from Rust #340.** The settings edit used 30.7337% and 30.7365% fewer whole-Cargo instructions than #337 on two fresh Linux boots. Both cold builds and the held-out edited test build exceeded the 1% cost limit on each boot. This ended the writer study at its two-block pilot. The prospective six-host follow-up did not enroll.

| Whole-Cargo command | Corrected change versus #337, boot 1 | Boot 2 |
|---|---:|---:|
| Ruff #28106 settings edit | −30.7337% | −30.7365% |
| Ruff #28106 independently empty build | +2.6301% | +2.6327% |
| Ruff #27836 edited server test build | +1.8362% | +1.8953% |
| Ruff #27836 independently empty test build | +3.2805% | +3.2663% |
| Ruff #28106 first unchanged build | +0.0549% | +0.0383% |
| Ruff #27836 first unchanged test build | +0.0014% | +0.0011% |

The candidate also reduced the settings edit by 4.8107% and 4.8171% against C3b in the same two boots. It reduced C3b’s cold and held-out costs, which all remained above the limit against #337. After the settings edit, the candidate added 5,881,856 and 5,836,800 allocated bytes against #337. After the held-out edit it added 7,147,520 and 7,081,984 bytes. RSS varied by host. The 36 unrounded instruction counts, allocation and kernel maximum descendant RSS are provided for every role and phase. These two mirrored blocks are descriptive. [All absolute values](absolute-prices.md), [separate fold decision](fold-result.json), [enrolled project rule](prespecified-fold-gate.json).

Both independent processes used baseline Rust 531eb1980c08c75ccbf3f6b77adbee53cd9b8bd5 (#337), previous writer ed0262f9bdc384576925229764971f23a141c95f (C3b), and corrected writer fba2663650927209e3589fdc807194f66271bd5a. One boot ran these three in order with settings first. The other reversed both orders. The counter includes ordinary Cargo and all inherited user-mode instructions in descendant processes. The settings edit physically ran one full rustc and its first repeat ran zero. The edited server test command ran two true rustcs and one native linker. Its repeat ran one checked link-only compiler and one linker. Both independent hardware readers reopened the entire raw archives, checked the actual executables and command lines, native test/diagnostic/repair/clean outputs, and full counter bytes. [Source and registration](../../selected-study.json), [matched compiler receipts](../../physical-factory.json), [physical acquisition and independent readers](https://github.com/astral-experiments/ohm/actions/runs/41561666391).

The earlier unscored native workers independently qualified the corrected source and both key-version migrations. The settings history accepted 15 of 21 dirty objects forward and 14 in reverse. One corrupted stored object fell back to LLVM. An invalid index made every dirty unit fall back. In each old/new key crossover the compiler opened the altered index, rejected that record, still reused 14 dirty units, and produced all 125 independently correct native objects. The held-out history included the newly added test, intentional failure and repair. The source and public native packet include the original acquisition’s job-name lookup failure and its separate successful reader. [Native, clean, corruption and migration receipts](../fba26636-native/README.md).

| Boot ID | Full original ZIP bytes | Original SHA-256 |
|---|---:|---|
| 8e9a7444-715d-40f5-857b-2ca4b73101b9 | 297,378,549 | d92988b5ba8441fa4525ecc072793888f1b062246eb777be6a48e596256c55ec |
| 4f1bda28-bcd5-4983-92fc-f9661f5a2a09 | 297,386,397 | 7e81fe2c4865ebb978ded4c51f7d6f1d48e6dca3c052207289b0823780f45995 |

The result stores the two independent compact reader ZIPs, GitHub’s aggregate ZIP and the source/boot/archive identifiers. In a full checkout of this packaging QA revision, run `bash reopen.sh` from this directory. The verifier reconstructs and hashes all 36 original hardware records, compares the native prerequisites, reproduces the aggregate, recompiles the two public tables from absolute values, applies the project decision using exact integer thresholds, and rejects five real altered hardware/native/source records. The separate study of six earlier P/C2/C3b measurements used different boots and contributes zero observations here. [Earlier six-host comparison](https://github.com/astral-experiments/ohm/blob/f7b79a0b1ee7ec48ee64cb2d0d981cc2a3879737/scripts/ruff-source-placement-c3b/evidence/six-source-boots/README.md).
