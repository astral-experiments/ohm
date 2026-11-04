# Lowering large static integer arrays on Ruff

On Ruff's switch to the new random number generator in its Unicode table generator, the complete affected rustc used 38.75% fewer instructions during an edited check and 36.18% fewer during a build. The entire Cargo commands saved 11.88% and 11.63%, respectively. We measured the unmodified historical Ruff sources and lockfiles. [Ruff edit](https://github.com/astral-sh/ruff/pull/29261)

## Measurements

| Command and measurement | Parent instructions | Changed instructions | Paired reduction | Range across six hosts |
| --- | ---: | ---: | ---: | ---: |
| check, edited rustc | 9.4287 B | 5.7748 B | 38.754% | 38.743% to 38.763% |
| check, whole edited command | 30.8111 B | 27.1520 B | 11.880% | 11.811% to 11.892% |
| check, whole cold OLD | 46.0741 B | 42.4242 B | 7.919% | 7.908% to 7.949% |
| check, whole empty NEW | 32.8628 B | 29.2064 B | 11.133% | 11.099% to 11.166% |
| check, rustc on empty NEW | 9.4295 B | 5.7747 B | 38.763% | 38.752% to 38.776% |
| check, whole unchanged | 0.1260 B | 0.1260 B | -0.008% | -0.022% to 0.009% |
| build, edited rustc | 10.1032 B | 6.4478 B | 36.181% | 36.161% to 36.187% |
| build, whole edited command | 31.4393 B | 27.7821 B | 11.628% | 11.603% to 11.661% |
| build, whole cold OLD | 47.1272 B | 43.4717 B | 7.755% | 7.735% to 7.778% |
| build, whole empty NEW | 33.9125 B | 30.2573 B | 10.775% | 10.749% to 10.815% |
| build, rustc on empty NEW | 10.1032 B | 6.4489 B | 36.171% | 36.153% to 36.186% |
| build, whole unchanged | 0.1282 B | 0.1282 B | -0.004% | -0.011% to 0.011% |

The parent and changed columns are medians for each arm. Each reduction is the median of the six paired percentage reductions. All six independent hosts improved on the primary metric, the complete `unicode_names2` rustc process during an edited check. Its minimum and maximum form a distribution-free 96.875% confidence interval for the paired median under independent sampling. The exact two-sided sign test gives p = 0.03125. Two separate pilot hosts cleared the preregistered 20% threshold before we dispatched these six. [Registration](../registration.json) · [Pilot](https://github.com/astral-experiments/ohm/actions/runs/41741463395) · [Confirmation](https://github.com/astral-experiments/ohm/actions/runs/41742406689)

Both compilers are source-matched stage 1 builds for Linux x86-64. The parent is the Rust revision from Ohm `-24`, `f5a51d8cc3e76236c2d0f17d495d59ebb03306e4`. The changed compiler is `6c2874a0b6a0bf3570f8959733b6f87907e5cce6`. Each arm uses the same signed Cargo and Wild binaries from that release. The Rust PR adds a regression test after the measured compiler commit. [Compiler transports](../transports.json) · [Release](https://github.com/astral-experiments/ohm/releases/tag/ohm-1.99.0-24)

The command was `cargo +ohm check -p ruff_unicode_names2 --lib --locked --offline`, or the corresponding `build`. Each arm started with its own target directory, shared build directory and Cargo home. We built the old revision, applied the historical edit to the checkout, built again, and ran an unchanged command. Old, edit and empty-new rebuilt 20, 11 and 17 units, respectively. The unchanged command rebuilt zero. We verified the 502 unique registry archives against the two original lockfiles. The whole-command count comes from an ordinary run. A separate history measured every thread during the selected physical rustc's lifetime, checked its executable and arguments, and reproduced the same outputs. Both counters use retired user-mode instructions and reject multiplexing. [Measurement program](../price.py)

## Outputs and storage

Both compilers produced clean-equivalent metadata after the edit. In each arm, the ordinary edited, repeated, repaired and empty-target native consumers matched byte for byte. The native reader tested 153,626 named Unicode characters in both directions, all 481 historical aliases and three unknown spellings. A deliberately overflowing table failed twice at the edited literal. An independent local history measured 95,678,292 → 73,123,506 bytes for the whole check target and shared build directory combined after the edit. The build directories measured 103,362,544 → 80,680,737 bytes. We counted hard-linked files once. [Storage](storage.json)

We verified the bytes and alignment of seven real data symbols on both little-endian x86-64 and big-endian s390x. Their values cover the fast path, an allowed overflow, a suffixed literal, a field attribute and a shorter array. [Object data](target-byte-order.json)

A separate Ruff change to loose Unicode-name matching measured 20.0280% and 19.9855% less edited-check rustc work. It missed the two-pilot admission criterion. A different edit to the alias list reproduced a 26-byte difference between incremental and clean metadata even on published `-24`. Two duplicate anonymous string allocations in the parent compiler account for the difference. We excluded that workflow from these measurements. [Loose-matching pilot](https://github.com/astral-experiments/ohm/actions/runs/41740052938) · [Alias allocation records](alias-allocation-difference.json)

## Reproduction

The reader reconstructs all eight original Actions artifact ZIPs byte for byte, verifies their SHA-256 digests, recomputes the physical rustc and ordinary-command counts, and checks each output. On x86-64 Linux, it can also execute every distinct retained program and validate the full native output. The 6,353,747-byte packet contains the complete 174,267,585 bytes of original artifacts, with identical compressed members shared across ZIPs.

```sh
python3 -IB scripts/ruff-static-array-cost/evidence/verify.py --run-native
```

Supply `--gh-auto /home/dev-user/.local/bin/gh-auto` from a configured checkout to check GitHub's original artifact digests as well. The local proof works after the Actions artifacts expire. To repeat the six measurements while both input compiler artifacts are retained, use the exact reviewed workflow below. The compiler transport records identify the two original factory runs and their reviewed workflow revisions for rebuilding those inputs.

```sh
/home/dev-user/.local/bin/gh-auto workflow run ci.yml -R astral-experiments/ohm \
  --ref charlie/qa-rc24-static-rand-cost-20261103 \
  -f reviewed_head=2730f118ffbe51cb7091360c6ea44b9c1b2bc600
```
