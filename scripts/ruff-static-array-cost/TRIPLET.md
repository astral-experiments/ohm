# Three release-trained compilers on Ruff’s Unicode generator edit

The primary measurement is the full `unicode_names2` rustc process on the real edited `cargo +ohm check -p ruff_unicode_names2 --lib --locked --offline`. We measure the cumulative F5→C7 change and the additional C5→C7 change separately. The release-trained C5 measurement is the positive control from #353. Whole ordinary Cargo check, whole ordinary Cargo build and the true build-rustc process are separate endpoints. [Ruff edit #29261](https://github.com/astral-sh/ruff/pull/29261) · [Source and gates](registration.json)

| Arm | Rust source | Release-recipe factory |
|---|---|---|
| F5 | `f5a51d8cc3e76236c2d0f17d495d59ebb03306e4` | [41737296261](https://github.com/astral-experiments/ohm/actions/runs/41737296261) |
| C5 | `6c2874a0b6a0bf3570f8959733b6f87907e5cce6` | [41742694783](https://github.com/astral-experiments/ohm/actions/runs/41742694783) |
| C7 | `06fe634feaa39288210a6f17b8994346a5fae1c1` | [41756960897](https://github.com/astral-experiments/ohm/actions/runs/41756960897) |

The commit between C5 and C7 changes one run-make test. The compiler, standard library, bootstrap and lockfile trees at C7’s parent equal C5’s. F5 and C5 already have independently trained SDKs. The initial registration refuses before touching a hardware counter until the exact C7 lib/rustc_driver, SDK and qualification archive from the specified source factory are authenticated. Every arm checks the same release Cargo, Wild, stage-2 build script, ThinLTO configuration and four training profiles. [Source ancestry and prior software observations](preexisting-software.json) · [Transport binding](transports.json)

## What the software observation covers

On the original OLD→NEW edit, both generated hash tables contain 13,490 `(u16,u16)` entries and 40,470 Rust `char` entries. The census parses each value in order and checks the complete file and typed, little-endian values against the fixed OLD and NEW SHA-256s. It distinguishes the explicit `&'static` in OLD from NEW’s elided spelling through the full source hashes. The rest of the generated files are also bound. [Typed inputs](rng-tables.json)

The existing stage-1 Callgrind originals for the complete edited rustc contain 9,489,390,493 (F5), 5,830,046,582 (C5) and 4,744,397,650 (C7) simulated instructions. The cumulative simulated ratio is 2.000125×. The previous six release-trained F5/C5 hardware pairs would require C7 to reduce C5 a further 20.94–21.66% to reach 2× at those measured ratios. The simulator’s incremental reduction is 18.62%. This three-compiler hardware comparison decides the actual ratio. [Raw-profile and selected-command identities](preexisting-software.json)

## Admission and decision

Two new boot IDs receive F5, C5, C7 and C7, C5, F5 respectively. Every arm installs at the same absolute SDK, Cargo home, target, shared build and checkout paths. The archived build states are isolated. The worker removes only its completed role’s temporary histories and installed SDK after the measured command, full correctness gates and evidence capture. Each run uses the original 502 authenticated package archives and authentic Ruff commit and lockfile for each state.

Both pilots must have at least a one-third reduction from F5 to C7 on the full edited check compiler, at least 10% from C5 to C7 and at least 20% on the F5→C5 positive control. **The ordinary full edited Cargo check must also favor C7 over both F5 and C5 on both boots.** A failed guard preserves the originals and prevents six-boot promotion.

The six independent confirmation boots use each permutation once. All six primary contrasts must be favorable with medians above or equal to those same thresholds. Every ordinary edited check must favor C7 over each predecessor. For the distinct cumulative 2× claim, every raw F5 count must be **strictly greater than twice C7**. Equality or a single slower ratio declines that claim. With six independent pairs, the minimum and maximum give a 96.875% nonparametric median interval and six strict wins give an exact two-sided sign-test p-value of 0.03125 against ratio 2. A material smaller gain is reported separately. The score checks the 2× gate with integer arithmetic. [Decision and veto implementation](triplet.py) · [Boundary tests](test_triplet.py)

For either predecessor, withhold on a cold OLD or settled complete command that regresses consistently in one mode by both more than 5% and more than 10 million instructions. Independently scan the delivered target and shared build trees after ordinary edit, settled and uninstrumented empty NEW. Charge each regular inode once across both roots, preserve its path aliases, and report both logical and allocated bytes. A consistent increase from either predecessor above both 2% and 1 MiB in any of these enrolled mode/state/size endpoints also vetoes promotion.

The uninstrumented whole command runs before a bounded observation of the same restored ordinary donor. The reopener independently matches the selected rustc’s physical exec/argv record and unscaled counter lifetime. It separately opens all Cargo messages and raw whole-command PMU records, and requires terminal success, expected dirty units and zero dirty units on settled. The protocol preserves ordinary and separately observed empty NEW. No test runtime enters a construction clock.

## Output and refusal controls

* Rebuild and run the genuine all-Unicode reader outside the timer. OLD and NEW ELF bodies must differ. Edited, settled, repaired and independently empty NEW must agree within each compiler on the complete reader, the 6,002,772-byte behavior stream and all 15 typed rlib members after the pre-existing verified rustc temporary-name adjustment. Every canonical name, alias and negative witness is checked. Check-mode rmeta digests must match across the corresponding within-arm edited and empty histories.
* Append unmeasured malformed declarations only after the unmodified NEW observed command. Each arm must reject a u8 overflow, a u16 tuple-field overflow and a u32 in a char array twice, at the exact new code and source span. Restore the original Ruff file, confirm a clean working tree, rebuild and compare to an empty build.
* Before any Ruff prices, run each actual trained SDK through the original integer-table probe and a separate tuple/char/layout probe. The integer THIR marker is `IntArrayLiteral` in C5 and `LiteralArray` in C7. The tuple/char probe expects four new typed markers on C7 and zero on F5/C5. It checks nested fields, padding fallback, two distinct named static addresses, a repeated invalid u16 and edited/empty native output. [Integer probe](array_probe.py) · [Tuple/char probe](aggregate_probe.py)

## Reopen

From the registered QA checkout, run the pure controls with `python3 -IB scripts/ruff-static-array-cost/test_triplet.py`. After an authorized pilot is complete, the following command downloads both complete originals, checks their Actions metadata and SHA-256, opens the actual data, executes the retained readers and writes raw per-arm counts and decisions.

```sh
python3 -IB scripts/ruff-static-array-cost/receive_triplet.py "$run_id" "$registered_qa_sha" "$new_results_directory" \
  --gh-auto /home/dev-user/.local/bin/gh-auto --run-native
```

A later six-boot receiver also takes `--pilot` with the admitted original pilot readback. Preserve a terminal refusal, all complete originals and their identities if any gate fails. This branch has no release entry point. [Independent source and native counter receiver](receive_triplet.py)
