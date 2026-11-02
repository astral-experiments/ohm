# Reopen six complete Ruff CLI builds

The source experiment uses `cargo +ohm build -p ruff --bin ruff --locked --offline -j4`. Each independent boot runs both physical stage1 compilers in the registered PC, CP, PC, CP, PC, CP order. The cold build uses Ruff revision B (`7b13f01ba1569887a25670820764b24c206da8e5`). The edited build, unchanged build, error and repair use revision A (`b5dba861cc38e3f7fb4524c9ceba3e01a474ea13`). The counters enclose the ordinary Cargo command. [Source workflow](https://github.com/astral-experiments/ohm/actions/runs/41433784058) · [Frozen protocol](https://github.com/astral-experiments/ohm/blob/dcf095ed65b3529c231560bee0c5e10fdf76b282/scripts/ruff-upstream-mono-pilot/bucket-protocol.md)

The reader requires a completed first attempt, the exact producer head, all six job names and recorded runner identities. It registers the artifact IDs, lengths and SHA-256s before opening an archive. The producing job's timestamped upload log must independently confirm its archive name, length, ID, digest and URL. Every complete ZIP is hashed before extraction. The factory receipt binds all 64 file digests in each installation, including rustdoc. [Compiler factory](https://github.com/astral-experiments/ohm/actions/runs/41431225435) · [Independent normal-layout qualification](https://github.com/astral-experiments/ohm/actions/runs/41432334895)

The producer's authenticated `read.py`, `live_family.py` and `normal_registry.py` reopen each arm's original clean binaries, Cargo streams, typed Ruff verdicts, E0308 and hardware counts. The receiver also reads the original per-filename physical identity and content hashes for both native owners and recomputes the signed 239 shared and 35 private registry archives on every successful measured and repaired visit. Between boots, each edited and cold clean parent ELF is either byte-identical to rank zero or passes the same complete audited `native_reference.compare` with its two actual jemalloc build directories. It checks bytes outside the permitted debug sections and GNU build ID, resolves the differing DWARF string references, and compares the complete decoded macro records.

## Run on an isolated QA worker

Use the reader checkout as `qa` and the independent producer checkout as `producer` pinned at `dcf095ed65b3529c231560bee0c5e10fdf76b282`. The worker needs Python 3.11+, Git, gh, zstd, GNU readelf and at least 17 GiB free. An Actions token with repository contents and actions read permissions suffices. The workflow's local output contains only JSON.

```sh
reader=qa/scripts/ruff-upstream-mono-confirm-reader
receipts="$RUNNER_TEMP/confirmed-receipts"
python3 -IB "$reader/test_receiver.py"
python3 -IB "$reader/aggregate.py" 41433784058 --producer producer --out "$receipts" --register-only
python3 -IB "$reader/aggregate.py" 41433784058 --producer producer --out "$receipts" --work "$RUNNER_TEMP/confirm-scratch"
python3 -IB "$reader/durable.py" "$receipts/paired-clocks.json" --from-results "$receipts"
```

`summary.json` reports each observed parent and candidate count, even for a slower candidate. `A` is the edited primary metric, `B` is cold, and `unchanged` is the immediate second invocation. Paired reduction is `(P − C) / P`. Six independent qualified pairs receive the exact two-sided sign test with ties omitted and the exact 96.875% median interval from the smallest and largest signed reduction. An intact experiment can finish with `edited_improved_on_all_six: false`. An incomplete experiment retains its usable per-rank records and refuses six-boot inference.

Per-rank JSON contains the original clocks, physical object ledger, named donor groups, complete native output SHA-256s, storage, graph nodes/edges/bytes and process counters. The compact `paired-clocks.json` retains all original clock fields and source archive IDs/digests, native reference identities and counterpart resource deltas. The offline command rechecks the raw-count arithmetic and cross-boot source and native identities after Actions artifacts expire. Independent byte-level ELF inspection requires the original native archives.

```sh
python3 -IB scripts/ruff-upstream-mono-confirm-reader/durable.py scripts/ruff-upstream-mono-confirm-reader/results/41433784058/paired-clocks.json
```
