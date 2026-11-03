# uv #22958 on Ohm 1.99.0-23

Both comparisons replicated at least 20% fewer retired instructions for `uv_client` and for the two rustcs combined. The median reduction for `uv_client` was 29.15–29.20% across the four hosts, and the two-rustc sum fell 23.64–23.68%. Bare Cargo wall speedups ranged from 1.259× to 1.291×. Each host missed the registered 2× wall threshold.

The workload was the first ordinary `cargo check -p uv-client --locked --offline -j8` after applying the landed edit to a fully checked A history. The actual source commits were `8ca75796365f348e25d3f7bea9daa1440218d40b` and `362613dbf38f60fe285cdd6bca53641149a23c04`. Exactly two workspace rustcs emitted products on the first edit. [uv #22958](https://github.com/astral-sh/uv/pull/22958)

**S/F** isolates Ohm Rust #327, #328 and #336 on the #318-corrected base. **R/F** measures the addition of all four changes to the published GNU toolchain. R was signed Rust `d57fd151`, S was `b5bbf6e7` and F was `60bd529e`. Every role used signed Cargo `7024b0d2` and the SHA-256 digest `f7cfe387ec3bd7e2e367d80596f379349faa23530194bf7cd7ba80a33adc6dee`. The original release and the two production-built SDKs are identified down to the installed members. [Release and SDK hashes](reader/signed-23-split-lock.json) · [Build and benchmark source](https://github.com/astral-experiments/ohm/tree/aca48cdac3a4c37076a4e91ef53efa17d0144efc/scripts/uv-client-22958)

Each host contributed eight paired first edits in two balanced blocks of four, from 16 independently built A histories. In each block and each individual pair, a registered instruction endpoint needs at least 20% fewer retired instructions and bare wall needs strictly more than 2×. Only a qualifying primary endpoint can replicate. Per-rustc PMU, inherited whole-Cargo PMU and unwrapped blocking-wait wall came from separate restorations of each same A seed. Whole-Cargo instructions are a descriptive endpoint. [Preregistration](reader/split-prospective.json) · [Decision rule](reader/release23_verdict.py)

## S/F

| Host | Retired userspace instructions | Control median | F median | Median paired reduction | Pairs ≥20% |
|---|---|---:|---:|---:|---:|
| primary 1852 | `uv_configuration` | 1,462,058,630.0 | 1,278,838,263.0 | 12.53% | 0/8 |
| primary 1852 | `uv_client` | 2,942,924,410.0 | 2,084,684,313.5 | 29.16% | 8/8 |
| primary 1852 | Two rustcs summed | 4,404,996,226.0 | 3,363,551,490.0 | 23.64% | 8/8 |
| primary 1852 | Whole Cargo process tree | 5,248,814,910.5 | 4,207,412,220.0 | 19.84% | descriptive |
| repeat 1854 | `uv_configuration` | 1,462,048,752.5 | 1,278,848,065.5 | 12.53% | 0/8 |
| repeat 1854 | `uv_client` | 2,942,982,866.0 | 2,084,696,473.5 | 29.16% | 8/8 |
| repeat 1854 | Two rustcs summed | 4,405,040,966.5 | 3,363,550,487.5 | 23.64% | 8/8 |
| repeat 1854 | Whole Cargo process tree | 5,248,908,824.0 | 4,207,398,762.0 | 19.84% | descriptive |

| Pair | primary S s | primary F s | primary speedup | repeat S s | repeat F s | repeat speedup |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.794 | 0.637 | 1.247× | 0.806 | 0.632 | 1.275× |
| 2 | 0.791 | 0.611 | 1.294× | 0.961 | 0.618 | 1.555× |
| 3 | 0.788 | 0.616 | 1.279× | 0.802 | 0.650 | 1.233× |
| 4 | 0.829 | 0.612 | 1.353× | 0.842 | 0.693 | 1.215× |
| 5 | 0.783 | 0.620 | 1.262× | 0.972 | 0.782 | 1.244× |
| 6 | 0.802 | 0.624 | 1.284× | 0.939 | 0.661 | 1.421× |
| 7 | 0.789 | 0.629 | 1.254× | 0.876 | 0.728 | 1.202× |
| 8 | 0.777 | 0.634 | 1.226× | 0.915 | 0.698 | 1.310× |
| Median | 0.790 | 0.622 | 1.270× | 0.895 | 0.677 | 1.259× |

Runner 1852 recorded block median wall speedups of 1.286× and 1.258×. 0/8 individual wall pairs exceeded 2×. [Original Actions run 41577930987](https://github.com/astral-experiments/ohm/actions/runs/41577930987)

Runner 1854 recorded block median wall speedups of 1.254× and 1.277×. 0/8 individual wall pairs exceeded 2×. [Original Actions run 41579572319](https://github.com/astral-experiments/ohm/actions/runs/41579572319)

## R/F

| Host | Retired userspace instructions | Control median | F median | Median paired reduction | Pairs ≥20% |
|---|---|---:|---:|---:|---:|
| primary 1853 | `uv_configuration` | 1,462,279,693.5 | 1,278,837,612.5 | 12.54% | 0/8 |
| primary 1853 | `uv_client` | 2,942,562,374.5 | 2,084,716,344.5 | 29.15% | 8/8 |
| primary 1853 | Two rustcs summed | 4,404,830,553.5 | 3,363,557,711.5 | 23.64% | 8/8 |
| primary 1853 | Whole Cargo process tree | 5,248,706,408.5 | 4,207,455,513.5 | 19.84% | descriptive |
| repeat 1855 | `uv_configuration` | 1,462,278,450.0 | 1,278,840,969.0 | 12.54% | 0/8 |
| repeat 1855 | `uv_client` | 2,944,727,258.5 | 2,084,729,498.0 | 29.20% | 8/8 |
| repeat 1855 | Two rustcs summed | 4,407,032,376.0 | 3,363,568,295.0 | 23.68% | 8/8 |
| repeat 1855 | Whole Cargo process tree | 5,250,967,395.0 | 4,207,518,268.5 | 19.87% | descriptive |

| Pair | primary R s | primary F s | primary speedup | repeat R s | repeat F s | repeat speedup |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.964 | 0.726 | 1.328× | 0.790 | 0.616 | 1.281× |
| 2 | 0.882 | 0.721 | 1.224× | 0.780 | 0.612 | 1.275× |
| 3 | 0.883 | 0.677 | 1.305× | 0.795 | 0.611 | 1.301× |
| 4 | 0.892 | 0.679 | 1.314× | 0.783 | 0.609 | 1.285× |
| 5 | 0.888 | 0.689 | 1.288× | 0.800 | 0.615 | 1.300× |
| 6 | 0.871 | 0.690 | 1.263× | 0.800 | 0.618 | 1.294× |
| 7 | 0.884 | 0.683 | 1.294× | 0.782 | 0.620 | 1.261× |
| 8 | 0.867 | 0.684 | 1.267× | 0.787 | 0.616 | 1.277× |
| Median | 0.884 | 0.687 | 1.291× | 0.788 | 0.615 | 1.283× |

Runner 1853 recorded block median wall speedups of 1.310× and 1.277×. 0/8 individual wall pairs exceeded 2×. [Original Actions run 41578145223](https://github.com/astral-experiments/ohm/actions/runs/41578145223)

Runner 1855 recorded block median wall speedups of 1.283× and 1.286×. 0/8 individual wall pairs exceeded 2×. [Original Actions run 41579685157](https://github.com/astral-experiments/ohm/actions/runs/41579685157)

Times are seconds. Speedups divide control by F within each pair. Reductions take the median of the eight F/control ratios. Each host’s control ran first in pairs 1, 4, 6 and 7. Integer counts, nanoseconds, per-host declarations, both block medians and the external repeat decisions are available in the machine-readable results. [Paired results](paired-results.json)

## Native admission

The published R compiler’s canonical five-visit CTFE fixture produced different public hashes on warm and independent cold B, and matched on C. Both independent stock uv openings passed the uv-specific tests. The original single-choice classifier therefore refused twice, before scoring. The split registration then admitted R as a control for this particular edit, and both private arms carry the CTFE correction. [Canonical signed CTFE receipt](receipts/signed-ctfe.json) · [Original classifier refusal](receipts/stock-opening-refusal.log) · [Two independent uv openings](reader/split-pair.json)

Every measured role passed dependency and ABI checks on the installed SDK. Across each opening, all 423 public sidecars matched on warm and independent cold B. Both no-edit observations had zero emitting compilers. The B-only schema import changed from E0432 to success and the linked program printed `"preview"` for all four agreed inputs. The unchanged client methods worked and the wrong client type retained E0308. The same-seed native and measured compiler arguments and product inventories agree for all scored visits.

| Host | Role | Independent cold workspace files with different bytes, of 39 | All differing inputs recorded in the cold comparison | Owners with extra fixed-input checks |
|---|---|---:|---:|---|
| 1852 | S | 4 | 4 | uv_client |
| 1852 | F | 5 | 6 | uv_client, uv_extract |
| 1854 | S | 5 | 6 | uv_client, uv_extract |
| 1854 | F | 4 | 4 | uv_client, uv_extract |
| 1853 | R | 5 | 6 | uv_extract |
| 1853 | F | 5 | 5 | uv_client, uv_extract |
| 1855 | R | 4 | 5 | uv_client, uv_extract |
| 1855 | F | 4 | 4 |  |

The independent cold comparisons retained raw byte differences, including registry products where applicable. Their structured comparisons and per-owner 8/1/1/8-thread fixed-input checks are in the originals. Within each restored measurement seed, all 39 workspace files and 423 public sidecars matched the corresponding ordinary process. [Archive inventory and hashes](manifest.json)

## One instrumented compiler visit per role

On separately restored histories for this edit, the published R compiler entered the `typeck_root` provider **77 times**, and F entered it **3 times**. The complete `uv_client` processes executed **3,045,425,242** and **2,165,658,021** Callgrind guest instructions, respectively. External entries to the provider accounted for 741,685,228 and 33,796,571 guest instructions. The original headers bind these visits to PIDs 19162 and 19201 and the same 1,020 Cargo-authored compiler arguments. These single-visit guest counts are separate from the per-host hardware pairs above. [Profiles, exact source and counts](mechanism/result.json) · [Boundary reader](mechanism/replay.py)

The original F collector passed its native and profiler checks, then looked for `raw.<pid>` while its own `%p.%n` selector wrote `raw.19201.2`. An independent readback qualified that exact original against the PID, observed executable, complete argv and same-seed outputs. The packet preserves the original exit and its subsequent acceptance. [Original F refusal](mechanism/F-original-refusal.log) · [F native receipt](mechanism/F-native.json)

## Offline replay

Use Python 3.11 or later, GNU `sha256sum`, and the `zstd` command with reference-patch support. Allow 650 MiB of temporary space. From this directory run

```sh
sha256sum --strict --quiet -c SHA256SUMS
python3 -ISB replay.py --controls
python3 -ISB mechanism/replay.py | diff -u mechanism/result.json -
```

The replay reconstructs each original Actions ZIP byte-for-byte and checks its service run, job, artifact and boot. It reads the retired counts, event IDs, enabled and running nanoseconds, compiler PIDs and bare Cargo clocks. It checks both independent stock observations against the typed and linked results, reconstructs every endpoint and verifies the signed contrast’s earlier marginal boot. For each repeat it also verifies the external acceptance and host-exclusion records. `--emit` prints the raw table. `--primary-only` restricts verification to the two primary hosts.

The marginal primary is a single zstd frame split into two Git-sized pieces. The signed primary uses the exact marginal primary ZIP as its zstd reference. Each repeat uses its own contrast’s verified primary ZIP as the reference. The GitHub service SHA-256, exact reconstructed size, part hashes and compression dependencies are listed for each original. The receipt bundles retain verbatim API records, original early boot ZIPs and external decisions. [Manifest](manifest.json) · [Reader sources](reader/SOURCES.json)

The four measurements used separate boots and runner identities. Both repeat decisions include an additional authenticated calibration from the independent #22536 study. A fresh-directory replay reopened all 128 per-rustc hardware records, 64 whole-Cargo records, 64 bare clocks and the two guest-instruction profiles. [Additional boot originals](receipts/additional-calibrations.zip) · [Independent replay receipt](independent-replay.json) · [Fresh-directory verifier](reader/isolated-replay.py)
