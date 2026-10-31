# The O1 compiler change on a normal Ruff linked build

The first unchanged build after a real edit to Ruff’s Unicode table generator fell from 5.192B to 3.112B instructions on one worker and from 5.187B to 3.113B on the other, a **1.6680× and 1.6665× improvement**. The edit plus its first unchanged build improved **1.4312× and 1.4308×**. Both endpoints fell short of the registered 1.80× threshold for a larger study. All measured endpoints completed on both workers. [Measurement plan](https://github.com/astral-experiments/ohm/blob/d3193d6417188200e84ca6d12a140de5ed3a94f8/scripts/native-compiler-loop/linked-only/PLAN.md) · [Two native workers](https://github.com/astral-experiments/ohm/actions/runs/41163268493)

Both roles ran the following command on Ruff `93526150`. Each applied the same isolated Cargo profile setting, `[profile.dev.package.ruff_unicode_names2_generator] opt-level = 1`. Ruff’s normal profile leaves this host library at O0. P used Rust `c79998a5`, and C used the compiler change in tree `0d30133a68ccfb5771670ef5fee7720e1483f5dc`. Both used strict Cargo `761ea115`, signed -21 Wild, and the same physical rustup path. Worker 01 ran P/C and restored the historical arithmetic. Worker 02 ran C/P and applied it. [Compiler build and source binding](https://github.com/astral-experiments/ohm/actions/runs/41157899149) · [Historical Ruff edit](https://github.com/astral-sh/ruff/commit/bfedc614b7670b8766576b64afd426c292f8c2ce) · [Earlier check data](../README.md)

```sh
cargo +ohm build -p ruff_unicode_names2 --lib --locked --offline -j4 --message-format=json
```

| Whole Cargo instructions, parent to candidate | Worker 01 | Worker 02 |
| --- | ---: | ---: |
| Cold build | 33.418B → 31.485B (1.0614×) | 33.401B → 31.479B (1.0611×) |
| Neutral unchanged build | 5.203B → 3.103B (1.6766×) | 5.190B → 3.105B (1.6716×) |
| Historical edit | 8.568B → 6.502B (1.3178×) | 8.557B → 6.493B (1.3179×) |
| First unchanged build after the edit | 5.192B → 3.112B (1.6680×) | 5.187B → 3.113B (1.6665×) |
| Historical edit plus its first unchanged build | 13.760B → 9.614B (1.4312×) | 13.744B → 9.606B (1.4308×) |

A native group counter covered Cargo and its descendants. All 56 direct, fork, exec and thread calibration observations passed. Separate kernel traces bound each rustc to its physical driver and each linker PID to Wild. On both compilers and workers, cold builds ran 17 full compilers and one linker. Genuine edits ran two full compilers, `unicode_names2_generator` and `build_script_build`, and one linker. The unchanged build ran `build_script_build` and one linker. The same generator executables used by the full command measured about 4.69B instructions on P and 2.61B on C when run directly with fresh output directories. [Native process and counter verifier](proof.py)

Cargo accepted the supported toolchain on both compilers. The same first source kit under its former arbitrary path produced the original 30-byte untrusted-input marker. The working rustup layout uses the genuine private rustup proxy and preserves each kit file’s device, inode and ctime. Every role produced all three expected generated files and returned the same four Unicode lookup values. Warm and empty invalid builds both reported E0308. Their repaired readers matched the independently empty executable byte for byte. The 36 separate native-provider visits included held 83→47 replacements with the same device, inode, length and mtime, malformed rejection, removal, fresh references and observed linker/loader opens. [Registration and controls](https://github.com/astral-experiments/ohm/tree/d3193d6417188200e84ca6d12a140de5ed3a94f8/scripts/native-compiler-loop/linked-only)

Deduplicating allocated blocks by device and inode across the target and shared store gave **45.316 → 45.051 MiB** and **45.312 → 45.055 MiB** cold. After the edit and the repeat, the totals were **45.617 → 45.355 MiB** and **45.613 → 45.363 MiB**. GNU du agreed at every paid visit. Each 68-file compiler SDK separately occupied 739,188,736 B on P and 739,270,656 B on C, a difference of 80 KiB. These installations used fresh, separate build roots for P and C.

## Reopen the evidence

From this checkout, run the following offline. The second command prints the exact counters, native traces, unique storage, generator hashes, provider verdicts and reader identities.

```sh
python3 -IB scripts/native-compiler-loop/result/linked-rustup/packet.py
python3 -IB scripts/native-compiler-loop/result/linked-rustup/packet.py --full
```

The 6,634,820-byte content-addressed packet preserves every byte of all **1,088 regular source-archive members**, 547 on worker 01 and 541 on worker 02. It stores 754 distinct new payloads once and references 19 identical payloads that already exist in the previous native study’s verified archives in the parent directory. Its SHA-256 is `6e7d31b796f79fb6999bfda36c7f6c2c267be40b9b7e924a7fcd4fdf18e649dc`. The reader checks every individual digest, original file path and the two measured roles. It reconstructs all original regular members in memory. [Packet format and reader](packet.py)

The following optional command authenticates the original GitHub ZIPs and compares every reopened member byte for byte with the compact packet. If both files are already available locally, supply `--originals /path/to/their/directory` instead. The measured registration selected seven days of GitHub artifact retention. The default offline command uses this Git tree.

```sh
python3 -IB scripts/native-compiler-loop/result/linked-rustup/packet.py --download /tmp/ohm-linked-41163268493
```

| Worker | Original artifact | ZIP bytes | ZIP SHA-256 |
| --- | --- | ---: | --- |
| 01 | [13027948424](https://github.com/astral-experiments/ohm/actions/runs/41163268493/artifacts/13027948424) | 10,064,539 | `3a00bcd21a851a83c9bae9dce4e83eb8efa3a55e001777c4d73cfb2b2e65828e` |
| 02 | [13027853744](https://github.com/astral-experiments/ohm/actions/runs/41163268493/artifacts/13027853744) | 10,061,093 | `4ac71ceb0c5146540e654fcd5193af0cad289ba438a008d56e5b951f984daa07` |
