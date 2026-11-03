# Rustc private built-in derives on the original RUF009 change

This experiment measures the first ordinary Ruff check after all three files of Ruff #19021 change on a developer checkout. It uses the historical buggy parent `710c60f71358` and fixed child `b00f68a23ced`. Each source visit verifies the complete original Git tree and the 445 locked registry archives and two Git checkouts. Each compiler starts with empty dependency products, Cargo target, Ohm build directory, incremental cache and native outputs.

The source-matched parent rustc is `d57fd1515986`. Its candidate is `800fcd497d67`. Source factory [41598619513](https://github.com/astral-experiments/ohm/actions/runs/41598619513) built both with the same frontend, 53 standard libraries and stock Wild. The driver and its genuine rustdoc belong to each role. Both use the identical release-profile Cargo `7c5f8b2d570b` from [41602805652](https://github.com/astral-experiments/ohm/actions/runs/41602805652). The hardware endpoint is this exact stack. The separately qualified signed distribution and later mixed-version checksum repairs have their own evidence.

The selected Cargo tests the actual executing rustc for support and supplies the new private-derive flag for eligible checksum-verified local checked units. The raw kernel observers distinguish rustup proxies, capability probes and actual typed rustcs, including each executable driver mapping. Whole-command user instructions include Cargo and all children and threads. The primary and its kernel observations run in separate, independently empty histories. The native/error checks run outside the measured commands.

```sh
cargo +ohm check -p ruff --bin ruff --locked --offline -j4 --message-format=json
```

The separate signed-Cargo historical run established seven actual parent compiles after the edit. Its genuine settled floor was one `ty_python_semantic` rustc. Cargo reported six stale targets in each of those settled checks. The worker records the actual and reported rosters twice before and after the edit. Its reader verifies full dep-info and metadata identities, timestamps and bytes for every nominal-only consumer. Full rmeta bodies, per-definition public rows and outgoing dependency records are decoded on an independent worker. Every Cargo-reported compiled registry and Git product has a compressed body that the reader can reopen. A different externally compiled body in any successful same-role check refuses promotion. The two earlier modern ports retain their original failed agreements and contribute zero observations here.

A separate native history builds actual Ruff executables on the original source, edits, reverse visit and repair. Independent empty fixed builds require identical whole executables within each role. Four Python programs enforce both changed RUF009 diagnoses and stable positive/negative controls, including the actual messages and underline. Cross-role comparison requires identical full binaries or a complete section/DWARF accounting for the one previously qualified Cargo jemalloc compiler-directory substitution and its associated build ID. A real invalid Rust source must yield E0308 immediately and repair to clean. The releasability of earlier or later Cargo/Rust combinations is separately qualified.

The one PC pilot is unscored. It needs one or more real downstream skips, an actual producer, the seven-member parent roster, every correctness gate and a reduction of at least 10% on the primary edit. The eight reserved confirmatory hosts have four PC and four CP assignments frozen in `registration.json`. They require every edited pair to improve and a median reduction of at least 10%. The report separates the exact one-sided paired sign probability (1/256 if all improve) from balanced assignment inference over 70 permitted allocations. The pilot cannot contribute to either statistic. The reader preserves each absolute count and the independent original ZIP commitment.

From this exact packaging checkout the separate pilot can be reproduced with the command below. A confirmation additionally requires a separately verified admission file and compatible input-checking pair.

```sh
qa_head=$(git rev-parse HEAD)
/home/dev-user/.local/bin/gh-auto workflow run ci.yml \
  --repo astral-experiments/ohm --ref charlie/qa-ruf009-historical-capability-20261103 \
  -f phase=pilot -f reviewed_head="$qa_head"
```
