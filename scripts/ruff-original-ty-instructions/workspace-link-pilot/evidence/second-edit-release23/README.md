# Signed -23 reused 31 native outputs on the second Ruff edit and the build cost rose

The complete `cargo +ohm test --no-run --locked --offline -j4` workspace command in Ruff #29697 used 288.207 billion retired user instructions on the signed compiler and 301.431 billion on the candidate's second OLD→NEW edit. All 50 physical ELF hashes matched between the two edited builds. Eight signed ELF hashes genuinely changed across that source transition. The 31 outputs reused by the candidate also matched the independently empty signed NEW build. One of the two ineligible native targets, ty_python_semantic, differed from the empty build in both arms. The independent source and signed empty NEW builds matched one another on all 50 targets. [Original run](https://github.com/astral-experiments/ohm/actions/runs/41741905666) · [Frozen source](https://github.com/astral-experiments/ohm/tree/d68c5ce147ce6089d48f2524836ab663737c175f/scripts/ruff-original-ty-instructions/workspace-link-pilot) · [All 48 role decisions and 50-target comparisons](physical-second-edit.json.gz)

The measured command includes actual Cargo, rustc, cc, collect2, native discovery, input reads, output reads and the new output writes. The test executions and hashing for the external independent ELF inventory run after the meter. This single worker reached all 37 registered phases. Its full-output correctness gate failed, so none of its prices qualifies a product change.

| Ordinary source state | Signed, billions of instructions | Candidate, billions | Actual fresh native outputs, out of 48 |
| --- | ---: | ---: | ---: |
| Cold OLD | 6,282.287 | 6,382.539 | 0 |
| First edit | 284.838 | 329.328 | 0 |
| First unchanged | 80.011 | 63.799 | 47 |
| Second unchanged | 80.008 | 64.464 | 46 |
| Third unchanged | 80.006 | 63.538 | 47 |
| Ordinary return to OLD | 285.151 | 329.372 | 0 |
| Reapply genuine edit | 288.207 | 301.431 | 31 |
| Empty NEW | 6,283.209 | 6,382.939 | 0 |

On the second edit the candidate read the 12.225 GB of actual native inputs, read a further 1.770 GB of newly linked outputs to establish full donors, and kept 1.811 GB of disk blocks in previous generations while it replaced 31 outputs. These are sums across roles. Wall time on this one edit was 15.05 s signed and 15.59 s candidate. The prospective 32-role forecast missed one role. The whitespace integration target had taken an actual multiworker native link on the prior command and supplied no donor. [Complete original clocks and controls](hardware-and-native.json.gz) · [Forecast registered beforehand](https://github.com/astral-experiments/ohm/blob/5be9982699f588bbec890a880bab53153a166e97/scripts/ruff-original-ty-instructions/workspace-link-pilot/evidence/full-native-challenge/prospective-second-edit.json)

The genuine withheld OLD e2e binary failed on the NEW fixture in both arms. The NEW harness had the same 200 tests and passed the changed test. The four-byte `main`→`zzQA` symbols.o mutation selected the real earlier native archive, consumed the changed input, emitted the separately observed whole ELF `8c579fff30074179355f18b92e83ef24ba7649894dfd6b456f11fe306873eeb6` and returned 83 with no output. A malformed native archive, an in-place mid-read change, a corrupt existing executable and a real Rust E0308 each reached the expected native or compiler refusal and repair. [First refused experiment and independent ELF execution](https://github.com/astral-experiments/ohm/tree/e93310e851a287d5131e5aa5697bd0cc19915bd8/scripts/ruff-original-ty-instructions/workspace-link-pilot/evidence/full-native-challenge)

Five candidate stage/role pairs differed from their signed empty reference. Each ran a real full link with two or four workers after the eligibility check refused reuse. The differences were in the mdtest harness, parser fixtures twice, ty_module_resolver tests and ty_server e2e. The only differing recorded section contents in all five were the GNU build ID. The other 40–41 section records matched. No signed same-state command in this original recorded the same complete divergent hash. The artifact preserved section contents by digest, file length and the whole file digest. The unrecorded ELF header fields and padding cannot be reconstructed from these receipts. The exact whole-file comparison remains failed. [Five raw SHA pairs and native refusal records](sections-and-fallbacks.json.gz)

## Reopen

The first archive is 93,916,385 B with SHA-256 `941425ee53b9993f2337cf7d6a8f031ac2420e86e708751a0d3208b2af852713`. The second archive is 7,978,293 B with SHA-256 `9dc7adaa541bb2d2e9cc4c9287a6c56fa9b850fffad3218bf13c321572b52f9d`. Run from the QA checkout with access to its private Actions artifacts. The verifier returns the measured direction and the five expected native refusals. The stored compact receipts remain readable after the Actions archive retention period.

```sh
r=scripts/ruff-original-ty-instructions/workspace-link-pilot/evidence/second-edit-release23
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13284735996/zip > /tmp/41741905666.zip
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13249569672/zip > /tmp/41675206812.zip
python3 -IB "$r/verify.py" /tmp/41741905666.zip /tmp/41675206812.zip
```

The one-pass digest and input-sharing decision is in the [component attribution](DIGEST.md).

The separate stable signed -24 component ceiling can be checked before the subsequent optional edit-counter refusal on that worker. Download original artifact 13283611149 (run 41742164171, SHA-256 `7bae04f05025e8866aca064beb9ccb492dccb28fcb119853bae4989d0427900f`), then compare the full child and counter joins:

~~~sh
python3 -IB "$r/clock_coverage.py" /tmp/41741905666.zip /tmp/41742164171.zip > /tmp/actual-clocks.json
gzip -cd "$r/physical-image-coverage.json.gz" | cmp - /tmp/actual-clocks.json
~~~
