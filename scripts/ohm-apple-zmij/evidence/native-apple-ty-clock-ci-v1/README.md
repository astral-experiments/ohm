# Repeating a ty_server e2e test build after Ruff’s diagnostics fix

After the real edit, leaving the source unchanged and repeating `cargo test -p ty_server --test e2e --no-run` went from 4.097 s to 0.123 s, a median paired 33.35×. The signed Cargo comparison used the GitHub CI profile, which disables rustc incremental compilation for local Ruff crates. The combined edit plus first repeat went from 12.327 s to 8.250 s, or 1.494×. The original edit still linked the tested executable. [Ruff change](https://github.com/astral-sh/ruff/pull/28988) · [Original measurements](https://github.com/astral-experiments/ohm/actions/runs/41067920579) · [Actual compiler configuration](../native-apple-cargo-profile-v1)

| Whole Cargo endpoint | Parent median | Candidate median | Median paired speedup (96.1% interval) |
| --- | ---: | ---: | ---: |
| Real edit | 8.235 s | 8.128 s | 1.014× (1.009–1.022) |
| First unchanged | 4.097 s | 0.123 s | 33.35× (33.13–33.79) |
| Second unchanged | 4.075 s | 0.115 s | 35.41× (34.25–35.81) |
| Edit plus first unchanged | 12.327 s | 8.250 s | 1.494× (1.485–1.508) |

The twelve confirmation pairs used six of each order. The minimum first-repeat ratio was 30.70×. The balanced assignment test for a sharp 2× effect gives p=1/924. The two mirrored pilots have separate records. Timing includes any incidental work. Disk allocation in the measured target and shared build directories had the same median in both arms, 1,291.79 MiB. Retired-instruction counters on this macOS host could not be qualified for descendants.

The parent rebuilt `zmij` and the e2e crate and called the system linker on both repeats. With Rust #276 all three operations disappeared in the signed-Cargo configuration. Both roles linked the real edit and returned the same bytes as their own independent empty builds. The catalog went from 194 to 195 tests. We ran the existing test and the added deleted-document test after the edit. Both rejected the invalid edit with E0425 and recovered. Test execution occurred outside the timers. The pilot artifact contains the clean Mach-O images, native process traces and checks. The confirmation artifact contains the commands, timers, held-program verifications, full inventories and final empty builds. [Pilot artifact](https://github.com/astral-experiments/ohm/actions/runs/41067920579/artifacts/12984803537) · [Confirmation artifact](https://github.com/astral-experiments/ohm/actions/runs/41067920579/artifacts/12987703051)

This comparison uses the Cargo shipped in `-20`. Cargo #293 changes how potential native inputs are revalidated. Its developer-profile cohort has a separate registration, requires incremental rustc arguments plus saved codegen files, and retains the direct and transitive native-input replacement controls. [Developer-profile run](https://github.com/astral-experiments/ohm/actions/runs/41078503973)

The offline reader checks the allocation, all timers and process CPU values, reference image and catalog identities, native counts, interval and randomization test.

```sh
python3 -IB verify.py
```

With the two original artifact ZIPs, this command also reads the raw Cargo JSON streams, physical native events, complete reference Mach-O files, executed test results and file allocation records.

```sh
python3 -IB reopen.py pilots.zip \
  6dc5c90394b900cf1596678aad123b6d268d04f7934a74b2687945d95f06b980 rechecked.json \
  --confirmation confirmation.zip \
  --confirmation-sha 6e568f14966e443115ca8b9c8e539c82b89abda795e0368ec7282f97e1fe19a5
```
