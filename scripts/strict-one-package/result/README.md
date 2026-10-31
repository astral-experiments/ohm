# Optimizing Ruff’s Unicode generator package

Optimizing only `ruff_unicode_names2_generator` reduced instructions on an unchanged `ty_project` check by **1.771×**. The registered 2× threshold did not pass. A fresh optimized target was 1.01 MiB smaller. Switching an existing default target retained **388.23 MiB more** across the target and shared directories. [Registration](../PLAN.md) · [Native run](https://github.com/astral-experiments/ohm/actions/runs/41154300915)

The twelve independent Linux x86-64 workers ran both arms, balanced over arm order and forward/reverse direction of the real `ty_project` edit `32c5cd5d`. Each worker used the release-style strict Cargo `761ea115`, signed `-21` rustc `c79998a5`, its Wild linker and the original Ruff `93526150` lock. The only change was an external `[profile.dev.package.ruff_unicode_names2_generator] opt-level = 1` in the private Cargo home. The ordinary scored commands ran without compiler wrappers, syscall tracing or extra Rust flags.

```sh
cargo +ohm check -p ty_project --tests --locked --offline -j8 --message-format=json
```

| Whole-command user instructions | Default median | Package opt 1 median | Paired default/optimized median [96.14% interval] |
| --- | ---: | ---: | ---: |
| Original empty | 493.723B | 492.596B | 1.0023× [1.0021, 1.0024] |
| Unchanged before edit | 16.583B | 9.107B | 1.8211× [1.8203, 1.8227] |
| Real historical edit | 19.456B | 11.975B | 1.6250× [1.6238, 1.6256] |
| First unchanged after edit | 17.180B | 9.699B | **1.7711× [1.7705, 1.7720]** |
| Edit plus its first unchanged check | | | 1.6904× [1.6895, 1.6909] |

The interval spans the third through tenth paired values. Forward/reverse medians for the primary were 1.7713×/1.7707×. Each worker passed 28 direct, fork, grandchild, duplicate fork, exec and one/two-thread PMU control commands with complete event coverage. The edit-plus-unchanged row sums the two ordinary Cargo instruction counts within each arm. Wall time was not scored. [Raw paired verdicts](verified.json)

Exactly one of the 338 Cargo units and one of the 304 real cold rustc invocations changed optimization level, from 0 to 1 for `unicode_names2_generator`. All 303 other physical compiler invocations retained their levels, including the Unicode build.rs, `phf_generator` and the consumer. Both arms ran 48 genuine Wild links on a clean check. Both unchanged checks physically ran the same three full rustcs (Unicode build.rs, `ron`, `unicode_names2`), one Wild link and the generator. Both settings preserved checked overflow and debug assertions. The complete neutral generated Rust across all 24 arms was identical; every historical state matched its independently empty reference, every invalid source correctly failed with E0308, and every repair succeeded without that diagnostic. [Compiler and linker readback](reopen.py)

| Existing-target switch | Median instructions | Actual full rustcs / Wild | Dirty Cargo artifacts | Median bytes after the next check |
| --- | ---: | ---: | ---: | ---: |
| Default → package opt 1 | 108.025B | 16 / 1 | 17 | 1,184.225 MiB |
| Package opt 1 → default | 109.146B | 16 / 1 | 17 | 1,184.225 MiB |

Fresh steady-state median allocated storage was 795.998 MiB with defaults and 794.986 MiB with package opt 1. The cold budget and fresh-storage budget both passed. The larger mixed state retained 48.77% more than the default fresh state, missing the predeclared 10% and 80 MiB limits. All totals independently match a device/inode allocation ledger and GNU `du`. On the default→optimized transition, 356.09 MiB of the median increase was exclusive to `target/debug/incremental` and another 25.25 MiB belonged to inodes with aliases in multiple top-level areas. `ty_python_semantic` exclusively gained 216.68 MiB. On every host its old and new incremental directories each held a separate roughly 172.7 MiB Ohm check graph and 42.8 MiB query cache. Their full contents were not archived, so these figures establish separately allocated files, not byte-for-byte equivalence. [Per-inode accounting](storage.json)

Two of the twelve hosts also ran the ordinary linked-library command against a real one-hunk upstream generator edit from `bfedc614b7`. Default/optimized first-unchanged instruction ratios were **2.451× and 2.456×**, edit ratios 1.646× and 1.649×, and cold ratios 1.047× and 1.047×. Both linked programs matched their own empty output and returned the expected four Unicode codepoints. These are two secondary observations. The same hosts separately verified 36 native-provider commands covering an earlier library, same-inode/mtime 83→47 replacement, malformation, removal and independent empty references. All native reader verdicts and generated output matched. [Secondary and provider evidence](verified.json)

```sh
cargo +ohm build -p ruff_unicode_names2 --lib --locked --offline -j4 --message-format=json
```

The original 12 GitHub ZIPs and their metadata are included (79,213,480 bytes, 21,624 inner files). Every arm retained the exact neutral generator executable; its complete ELF SHA-256 was `9d9a0837b0233fda1e4abd51dcfc4e3c2c3a4ab01b41ad6fc460adc1b2f5dc1a` for all default workers and `a10dcb362a57bda3888794fd69f87d1174407fedc37de6dd0db178266f8d7d9a` for all single-package workers. This protocol measures an existing package configuration.

## Offline reproduction

From this directory, validate the original signed Cargo identity, each native phase, all 336 PMU calibrations, executable and generated-source bodies, and the registered paired decisions. The second command independently reopens the allocation explanation. The final command extracts one real optimized ELF and its exact rustc and Wild kernel arguments into a new directory.

```sh
python3 -IB reopen.py | cmp - verified.json
python3 -IB storage.py | cmp - storage.json
python3 -IB extract_elf.py one-package-01.zip one-package-01.json 01 1 ./generator-reader
```
