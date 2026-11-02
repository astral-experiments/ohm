# Whole-Cargo pilot for the post-optimization source placement prototype

Changing Ruff’s workspace option in #28106 reduced whole-Cargo retired user instructions by 17.20% on each of two independently booted x86-64 Linux runners. **The preregistered requirement was a 2× reduction on each boot. Both missed.** The separate #27836 e2e test-build edit and both cold builds used more instructions with the prototype. These two observations per case support a mechanism screen. They do not establish a population confidence interval. [Frozen registration](https://github.com/astral-experiments/ohm/blob/5b853a9f313227ce60ac43134a7070ef60bbca5b/scripts/ruff-source-placement/protocol.json)

| Ordinary command and phase | Boot 1, parent → candidate | Boot 2, parent → candidate |
| --- | ---: | ---: |
| Build `ruff_workspace --lib`, empty original checkout | 1,802.905B → 1,884.190B | 1,803.129B → 1,884.180B |
| Same build, real #28106 edit | 112.073B → 92.793B | 112.099B → 92.818B |
| Same build, immediate unchanged | 485.343M → 485.181M | 485.808M → 485.453M |
| Build `ty_server --test e2e --no-run`, empty original checkout | 2,151.705B → 2,274.240B | 2,151.874B → 2,273.937B |
| Same test build, real #27836 edit | 31.209B → 32.295B | 31.208B → 32.296B |
| Same test build, immediate unchanged | 3.356255B → 3.359760B | 3.356103B → 3.356035B |

The hardware counter covers the ordinary four-job `cargo +ohm` process and its userspace descendants and threads, including any native linker. The real edited option build invoked one full owner compiler on both roles. The e2e edit invoked two full compilers and one genuine Wild. Its unchanged repeat invoked a link-only compiler and one Wild. The CPU work for the e2e edit grew by 3.48% on both boots. Cold costs grew 4.50–4.51% for the option build and 5.67–5.69% for the e2e test build. [Original measurement and independent reader jobs](https://github.com/astral-experiments/ohm/actions/runs/41485360543)

For the option edit, allocated bytes in the combined target and shared build directories went from 1,600,786,432 to 1,606,631,424 on boot 1 and from 1,600,778,240 to 1,606,619,136 on boot 2. The measured maximum child RSS went from 843,848 to 950,184 KiB and from 863,476 to 943,688 KiB. For the e2e edit the corresponding allocations went from 2,343,755,776 to 2,350,850,048 bytes and from 2,343,718,912 to 2,350,907,392 bytes. Its maximum child RSS went from 725,200 to 753,084 KiB and from 735,600 to 757,248 KiB. The verifier prints absolute counts, allocated bytes and RSS for all cold, edited and unchanged cells. The combined allocation counts allocated blocks once per inode across both trees. The memory measurement is the kernel-reported maximum child RSS for each command. [Storage and RSS acquisition](https://github.com/astral-experiments/ohm/blob/5b853a9f313227ce60ac43134a7070ef60bbca5b/scripts/ruff-source-placement/worker.py)

The parent was `531eb1980c08c75ccbf3f6b77adbee53cd9b8bd5` and C2 was `4e546b27c311f29d99f9528e64420887f57c7538`. The source-built kits included their own genuine working rustdoc, and the same signed Cargo, Wild, standard library and LLVM. The off-counter acquisition found 13 placed objects among 21 dirty option CGUs. The remaining eight used ordinary machine-code generation. Prior hardlinks retained their contents. Deliberately corrupting a known previous object reduced placements to 12, and corrupting the optional index reduced them to zero. All 125 complete returned object bytes matched independent empty builds on both branch directions. The normal readers, e2e executable, contrary assertion, E0308, repair and check-then-build controls passed. [Matched compiler construction](https://github.com/astral-experiments/ohm/actions/runs/41475100027) [Native originals](https://github.com/astral-experiments/ohm/actions/runs/41478151188) [Independent native reopener](https://github.com/astral-experiments/ohm/actions/runs/41484352206)

The first final decision job stopped at its registered 15-GiB free-space floor before opening the counts. A second, roomier runner reopened the exact same four verified archives and ran the original decision code. Each of the five ZIP files here is the unchanged small Actions artifact from its independent reader. The large original trace and ELF archive IDs, sizes and digests are preserved in `receipts.json`. [Original refused receiver](https://github.com/astral-experiments/ohm/actions/runs/41485360543/job/125433103066) [Successful final receiver](https://github.com/astral-experiments/ohm/actions/runs/41492659316)

From this directory, run the following offline. The verifier checks the source and driver identities, genuine phase verdicts, original artifact digests, all 24 event/allocation/RSS observations and the unchanged 2× decision. Five mutation tests cover incorrect events, duplicate boots, a false corruption hit, a changed clean ELF and a reversed final decision.

```sh
sha256sum --check SHA256SUMS
python3 -IB verify.py --self-test
```
