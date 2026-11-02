# Production rustc build guard on uv #20992

The optimized compiler passed the registered build guard on the four-file edit from uv #20992. Across eight paired ordinary builds, the candidate took 96.4–99.7% of the parent’s elapsed time. The median candidate/parent ratios in the two independent holds were 0.9775 and 0.9888. All eight fell below the 1.10 ceiling (one-sided sign test, p = 1/256). The acceptance rule required both four-pair medians below 1.05 and at least seven pairs below 1.10. [Landed uv change](https://github.com/astral-sh/uv/pull/20992) · [Original benchmark run](https://github.com/astral-experiments/ohm/actions/runs/41442900507)

The parent was production Rust `77ce0545653d` and the candidate was `ac67101cb973`. Both were GNU x86-64 stage-2 PGO, ThinLTO and BOLT builds using the signed Ohm −22 Cargo. The command was `cargo build --locked --offline -j8 -p uv-cli`. Every observation restored the role’s native prior build and applied the authentic edit, with HEAD and the Git index at the parent commit. Cargo rebuilt the recurring `uv-python` build script and library on both sides. The edit also built `uv-cli`. The native openings checked the Cargo unit graph, linked archives, and all seven CLI outcomes at both revisions. The consumer ran outside the timed Cargo command. P denotes the parent and C the candidate.

| Pair | Order | Parent (s) | Candidate (s) | Candidate / parent |
| --- | --- | ---: | ---: | ---: |
| 1 | PC | 1.775615 | 1.712217 | 0.9643 |
| 2 | CP | 1.762377 | 1.725457 | 0.9791 |
| 3 | CP | 1.738840 | 1.729092 | 0.9944 |
| 4 | PC | 1.768447 | 1.726067 | 0.9760 |
| 5 | CP | 1.775428 | 1.731264 | 0.9751 |
| 6 | PC | 1.754484 | 1.749028 | 0.9969 |
| 7 | PC | 1.766414 | 1.741211 | 0.9857 |
| 8 | CP | 1.742991 | 1.728956 | 0.9919 |

The bare clock blocked on ordinary Cargo. Two separate restored visits per arm counted inherited userspace instructions for Cargo and its descendants, and measured the individual thread groups of its three actual rustc children. Median paired instruction reductions were 5.26% across the Cargo process tree and 6.10% in the edited `uv_cli` compiler. The recurring build script and `uv_python` changed by less than 0.03%. [All wall, CPU and instruction readings](panel.json)

## Replay

Run the verifier from an unpacked checkout with Python 3.11 or newer.

```sh
python3 -ISB verify.py
```

The packet includes exact service-member bytes for the blocking clocks, the Cargo output, all raw hardware counter words, kernel process events, native CLI outcomes, and the original decision. The verifier joins the compiler processes to their enrolled commands and independently calculates the eight ratios and both hold medians. It also compares the reported samples with `panel.json`. The file index contains the SHA-256 of every original member.

To reopen the complete artifact while GitHub retains it, authenticate to the private coordinator, save the service ZIP, and run the following commands from this directory. The full compiler-output replay uses the benchmark source already present in this commit.

```sh
artifact_dir=$(mktemp -d)
gh-auto api repos/astral-experiments/ohm/actions/artifacts/13141772334/zip > "$artifact_dir/original.zip"
python3 -ISB verify.py --original "$artifact_dir/original.zip"
unzip -q "$artifact_dir/original.zip" -d "$artifact_dir/native"
python3 -ISB ../../uv-library-build-20992/replay.py "$artifact_dir/native"
```

The service ZIP is 89,574,593 bytes with SHA-256 `bdba29b6c838c990db09061d970c9eafa72ac63cb8110a9964ea2c843b17fe72`. The full replay checks all four native histories, the selected real archives and their linked consumers, all declared same-seed outputs, and the counters. The separate study of ordinary `cargo check` has its own comparison and endpoint.
