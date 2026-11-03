# Recent Ruff's unchanged workspace test build still runs Ron and 50 links

This signed Linux Ohm `1.99.0-23` baseline ran the virtual workspace root at Ruff #29697. The edit adds supported script tags and source text to the debug command. This is one hardware host, two unchanged visits, and a separate set of traced visits on that host. There was no compiler treatment. [Ruff edit](https://github.com/astral-sh/ruff/pull/29697) · [Original first-attempt run](https://github.com/astral-experiments/ohm/actions/runs/41617756983) · [Independent original reader](https://github.com/astral-experiments/ohm/actions/runs/41619749913).

```sh
cargo +ohm test --no-run --locked --offline -j4 --message-format=json
```

All 55 workspace members were Cargo's actual defaults. The signed unit graph contained 693 units and 118 roots, including 19 doctest roots. Cargo published 102 executable paths. They comprised 6 binary, 35 library and 43 integration test harnesses, 15 examples and 3 ordinary binaries. The narrower `ty_server --test e2e` has a different graph and reaches zero fresh compilers and links. [Package-only control](https://github.com/astral-experiments/ohm/actions/runs/41613152535).

| Visit | Retired user instructions, ordinary Cargo | Typed rustcs, separate tracing | Link-only rustcs | Native links |
| --- | ---: | ---: | ---: | ---: |
| Empty OLD | 6,282,412,234,115 | | | |
| Real OLD → NEW | 284,727,953,657 | 30 | 33 | 57 |
| First unchanged | 80,003,069,913 | 1 | 50 | 50 |
| Repeated unchanged | 80,007,700,353 | 1 | 50 | 50 |
| Repaired after E0308 | 222,207,294,389 | | | |
| Independent empty NEW | 6,282,736,693,811 | | | |

Each unchanged traced visit had 56 dirty Cargo artifact records. Both ran one full `ron` compiler and executed all 50 native links via `-Zlink-only`. Every native destination belonged to one of those 50 rustcs. The actual Wild images retired 63,430,228,524 and 62,931,726,553 instructions including their forked workers, or 79.28% and 78.65% of the traced Cargo total. Ron retired 9,328,060,644 and 9,326,679,151 instructions in its compiler image. The reader separately binds genuine executable transitions by filesystem identity and complete argv, joins the actual kernel fork edges to the owning rustc, and lists inherited image intervals separately. Every positive counted interval had equal running and enabled time. Ordinary and traced dirty rosters agreed in both states. [Typed reader](../workspace29697_reopen.py) · [Clock, compiler, source and destination rosters](counts.json).

The old binary failed the edited snapshot on the expected `script_tag` and `source_text` fields. OLD, NEW, reverse, repair and independent empty NEW passed the named real test outside the counter. All seven visits listed the same 200 harness test names. Injecting a genuine E0308 returned 101 and yielded no accepted e2e executable. Independent NEW produced the exact edited e2e ELF. Of the 102 outputs, 14 changed on the source edit, and all 102 stayed byte-identical after both unchanged Cargo visits. Comparing the edit to independently empty NEW found 101 exact executables. The sole differing section hash in the remaining `ty_python_semantic` harness belongs to `.note.gnu.build-id`. Repair, reverse and traced histories have their own raw mismatch lists in the packet. The counter reader opens both original selected native ELFs in full. [Source and safeguards](../workspace29697.py) · [Pinned source/SDK registration](../workspace29697-registration.json).

The producer archive, ID `13223081435`, is 102,158,690 bytes with SHA-256 `2ab6618f9f643f0c2ef9c192192c3b4955fe02f378432c8c28f01f8f8718f677`. The independent JSON reader artifact, ID `13223590837`, is 145,484 bytes with SHA-256 `c79d3d6a3b338480bc9616073a6a11589ef5803bd4b78a5e6b366cfebe325073`. [Original artifact](https://github.com/astral-experiments/ohm/actions/runs/41617756983/artifacts/13223081435) · [Reader artifact](https://github.com/astral-experiments/ohm/actions/runs/41619749913/artifacts/13223590837).

To check the compact record, from this directory use the original independent `reopened.json` and run `python3 -IB project.py reopened.json | cmp - counts.json`. To repeat the ordinary whole workspace registration on a new Linux worker, run:

```sh
gh-auto workflow run ci.yml -R astral-experiments/ohm \
  --ref charlie/qa-current-ruff-workspace-test-29697-20261103 \
  -f reviewed_head=50b22d77297be3cad8a8ba72620992c54a5683bc
```
