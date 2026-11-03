# What fresh native input resolution and validation cost on Ruff

On the signed Linux `-23` workspace test build for Ruff #29697, this diagnostic preserved the ordinary Cargo, rustc, GCC and collect2 commands. A separate Wild 0.11.0 source executable replayed the 50 actual native argument vectors. It reproduced every byte of all 50 signed executables on this worker. Each phase count below covers a fresh process and all children, using retired user instructions with equal positive time enabled and running. The cutoff runs preserve the existing output. The benchmark never skipped a Cargo link. [Hosted original](https://github.com/astral-experiments/ohm/actions/runs/41675206812) · [Source patch](../../phase-diagnostic.patch) · [Per-target receipt](reopened.json.gz)

## One real ty_server e2e native chain

The signed chain used 3,640,286,481 instructions, including 34,812,878 in rustc, 12,241,025 in GCC, 515,074 in collect2 and 3,592,717,504 in Wild. This includes the exec and first fork epoch for each image. Its 409 native inputs occupied 618,902,647 bytes, including the ephemeral 39,760-byte `symbols.o`. The output occupied 227,979,336 bytes.

| Fresh component | Retired instructions |
| --- | ---: |
| Native file loading and library/script lookup, before symbol resolution | 35,057,084 |
| Same cutoff, also hashing every mapping with BLAKE3 | 673,443,586 |
| File loading through complete symbol and section resolution, before layout | 541,614,281 |
| Full source-built Wild | 3,589,333,678 |
| Standalone SHA-256 over all 409 inputs | 1,661,473,490 |
| Standalone SHA-256 over the complete existing output | 612,488,846 |

Each row uses the larger of forward and reverse counts where both were collected. Keeping the ordinary rustc/driver cost, real file resolution with BLAKE3 on every mapped byte, and independent SHA-256 over the existing output totals 1,333,501,409 instructions. That leaves 486,641,831.5 instructions under half of the observed native chain. Using file resolution plus separate input SHA-256 and output SHA-256 crosses half by 536,445,156.5. Full symbol/section resolution with those same SHA checks crosses half by 1,043,002,353.5. These are sums of physical component measurements. The cutoff process ran independently of the driver. [Every raw clock and both e2e orders](reopened.json.gz)

## Fifty actual destinations

The same executable rebuilt all 50 targets with the recorded native arguments and reproduced all 50 signed ELF hashes on this boot. On the e2e target the originally mapped objects and complete output replays passed the changed Ruff test, its withheld OLD negative, earlier-library/four-byte symbol challenge and malformed library recovery. All 50 file-resolution cutoffs totalled 967,081,865 instructions. Full symbol/section resolution totalled 11,476,994,690. File resolution plus BLAKE3 on each mapping used 14,637,019,828. [Behavior and boot readback](three-boots.json.gz) · [Typed resolver controls](../source-lookup/RESULTS.md)

There were 12,708 successful input occurrences with 13,202,067,252 bytes. A fresh in-memory sort grouped them into 3,465 distinct paths and 3,465 device/inode identities totalling 1,433,054,569 bytes. The ordered 32-bit occurrence index uses 50,832 bytes. Unique NUL-terminated paths occupy 842,332 bytes. Building the array, opening every distinct file, attempting read leases and computing its SHA-256 used 3,930,768,328 and 3,930,768,332 instructions. Separate SHA-256 on every occurrence used 35,405,448,329. The 50 outputs occupy 3,956,746,600 bytes and their separate whole-file SHA-256 scans cost 10,520,070,962 and 10,520,071,020 instructions. All 19 unleaseable inputs were present on the e2e link and total 7,627,189 bytes. They include system CRT objects, GNU scripts, static libraries, dynamic libraries and the ELF loader. The remaining 3,446 leases reported zero breaks during the standalone scan. [Source reader](../../phase_price.py) · [Complete file receipts](https://github.com/astral-experiments/ohm/actions/runs/41675206812)

**The preregistered same-boot aggregate attribution was refused.** The outer whole-workspace command counted 80,004,287,368 instructions. Its individually metered process epochs fell short by 5,385,730,141, exceeding the one-million-instruction conservation tolerance. Two Wild fork epochs reported less than 1% of their corresponding full source clocks. Another, earlier run missed 5,590,999,116 instructions. Both remain in the readback. The e2e chains themselves agreed across all three independent boots, and the independent native phase and scanner processes used separate inherited counters. [Three original epoch rosters](three-boots.json.gz)

The earlier conserving boot counted 80,007,961,071 for the workspace and 66,761,691,792 for its 50 signed Wild links. Retaining its 13,246,269,279 other instructions and substituting these independently measured costs gives the following **cross-boot sensitivity**. The destination roster was identical and 48 of the 50 cross-boot ELF hashes matched. The two different executables were `ruff-82a6b65b1d36d43c` and `ty-0099d1d7349a58e3`. Intra-boot full source/signed equality held for all 50. [Earlier conserving original](https://github.com/astral-experiments/ohm/actions/runs/41671338175) · [Earlier refused original](https://github.com/astral-experiments/ohm/actions/runs/41668727619)

| Substituted native work on all 50 | Including output SHA, billions | Budget below half of earlier whole command, billions |
| --- | ---: | ---: |
| File/script resolution + compact input SHA | 28.664 | +11.340 |
| Full symbol/section resolution + compact input SHA | 39.174 | +0.830 |
| File/script resolution + BLAKE3 on each mapping | 38.403 | +1.601 |
| File/script resolution + SHA on each occurrence | 60.139 | −20.135 |

Production would have to bind the original donor's bytes, the actual external driver/loader behavior, ordered namespace outcomes and a stable output generation through the reuse decision. This experiment did not acquire those guarantees. The 19 failed leases, input generations changed after the original link, missing search candidates and replacement of the output are material cases. Capturing and coordinating proof across normal processes also has an unmeasured cost. [Earlier native mutation and loader controls](../source-lookup/RESULTS.md)

## Reopen the originals

The primary artifact is `13249569672`, 7,978,293 bytes, SHA-256 `9dc7adaa541bb2d2e9cc4c9287a6c56fa9b850fffad3218bf13c321572b52f9d`. Set `OHM_BLAKE3_LLVM` to a local LLVM shared library exporting the standard LLVM BLAKE3 C symbols. From the repository root, run:

```sh
r=scripts/ruff-original-ty-instructions/e2e-wild-inputs/evidence/phase-price
python3 -IB "$r/read.py" /path/to/41675206812.zip \
  9dc7adaa541bb2d2e9cc4c9287a6c56fa9b850fffad3218bf13c321572b52f9d \
  3df90be58404442d739179f0c10c4894fe2e0392 41675206812 /tmp/phase-price.json
python3 -IB "$r/compare_boots.py" /tmp/phase-price.json \
  /path/to/41668727619.zip /path/to/41671338175.zip /path/to/41675206812.zip /tmp/phase-boots.json
```

The primary readback SHA-256 is `ab29199f24f47fb86d1ea05064d31e3f2a598946b839e1d4fd930e71a29bd190`. The second command independently authenticates the three original ZIPs and resolves every target to its real output roster and exec/fork epochs. It retains the full raw instruction counts of both refused boots.
