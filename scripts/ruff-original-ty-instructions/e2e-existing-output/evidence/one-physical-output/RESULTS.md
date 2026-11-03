# Reusing one native executable on an unchanged Ruff workspace test-build

On signed Linux Ohm -23, the ordinary workspace invoked the actual linker for the ty_server e2e test. A source-built Wild 0.11 diagnostic verified 409 selected native file bodies, 94 failed lookups, rustc's actual temporary symbols.o and the jobserver-dependent grouping. It published a freshly opened executable containing the authenticated bytes of the existing canonical output on three separate unchanged Cargo invocations. In each case the entire 227,979,336-byte ELF was identical to the new signed comparison. The independent empty NEW workspace and two further untouched signed warms produced that same full SHA-256, 86b94323a752a316a501f542a846408648ca8b74c56bc60298690b671b7b0563. All 102 Cargo products were present. [Completed original](https://github.com/astral-experiments/ohm/actions/runs/41723091119)

The pre-edit and genuinely edited source produced different complete e2e executables. Running the withheld OLD executable on the changed NEW fixture failed its real source_text/script_tag snapshot. NEW passed commands::debug_command with the same complete 200-name test inventory. The three hits each held the old inode unlinked through a new exclusive open and the complete 228 MB write. On the O_PATH challenge the old inode was 7767289 with 227,983,360 allocation bytes, and the published inode was 7766898. Writing through the old handle after publication preserved the entire new ELF. Only one canonical output was retained. The old inode can temporarily consume its full disk allocation while another process holds it.

The real canonical file initially refused an in-place writer with ETXTBSY, then accepted it on retry. The fixture flipped 0xee to 0xef in .text at file offset 30,621,714 and preserved size, timestamp and mode. Reversing this one byte restored the full signed-new SHA. Native validation rejected the damaged executable and a full real link repaired it. Earlier library search, atomic target replacement, a concurrent save, an exclusive-create collision, a four-byte native object change, a malformed native library, a mid-read rewrite and repair all ran on this head. The modified symbol selected the deliberately different provider and returned 83. The malformed input and in-flight rewrite each returned Cargo 101. The held collision sentinel remained byte-identical after normal native repair. [Independent safety projection](functional-4-safety.json)

Every count measures the complete workspace build, outside test execution. The three hit totals include the independently measured coordinator thread. The two untouched signed controls did not use the coordinator.

| Actual invocation | Retired user instructions |
| --- | ---: |
| Hit | 78,454,943,689 |
| Repeated hit | 78,556,948,886 |
| Hit with O_PATH reference | 78,466,200,547 |
| Source full-emission control, including coordinator | 81,828,376,958 |
| Untouched distributed Wild, first unchanged | 80,005,460,066 |
| Untouched distributed Wild, second unchanged | 80,001,690,275 |

The three observed hit totals were 1.81–1.94% below the untouched signed mean on this single boot. The candidate was a private source diagnostic for one link; the other native linkers ran the distributed Wild. This result selects the remaining 49 links for a separate full-emission opportunity census. [Original registration for all 50 roles](https://github.com/astral-experiments/ohm/blob/9ec1f2f6b7b3eed06350d8969d45f956a87249d0/scripts/ruff-original-ty-instructions/workspace-link-proof/REGISTRATION.md)

The GHA archive is 7,294,914 bytes, SHA-256 6dcff8bf78023a304b67be31f2156b8c853e3a332f0d66434bcd9daf8ee8d3a0. Its statically linked source diagnostic is d11b1d97d8fa7f5bc5f906d6fd4cfcea164a42747253c877a07a818cc16183f1; the exact distributed Wild is 0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5. The earlier refused experiments, grouped signed controls and exact source are retained on this branch. To reopen all three physical projections, run the following from this directory.

    gh-auto api repos/astral-experiments/ohm/actions/artifacts/13275840782/zip > original.zip
    python3 -IB read_functional.py original.zip 575582bd4f55f4410720e31ef04261b8238b8042 41723091119 6dcff8bf78023a304b67be31f2156b8c853e3a332f0d66434bcd9daf8ee8d3a0 > observed.json
    gzip -dc full-projection.json.gz | cmp - observed.json
    python3 -IB safety_read.py original.zip 575582bd4f55f4410720e31ef04261b8238b8042 41723091119 6dcff8bf78023a304b67be31f2156b8c853e3a332f0d66434bcd9daf8ee8d3a0 | cmp - functional-4-safety.json
    python3 -IB clocks.py original.zip | cmp - clocks.json
