# Ruff #27470 library-test build

The compiler used **43.54% fewer retired user-mode instructions** on Ruff’s real Old→New edit for `cargo +ohm test --no-run -p ruff_db --lib`. Across six independently initialized Linux x86-64 workers, the exact 96.875% interval for the median reduction was **43.47–43.60%**. The two-sided exact sign probability was **0.03125**. Each boot ran one P/C pair, with three parent-first and three candidate-first assignments. The earlier pilot contributed no measurements. [Six source workers](https://github.com/astral-experiments/ohm/actions/runs/41442143564)

All six candidate histories retained 216 of 216 original caller objects, compared with 178 for the parent. The edited test ELF matched an independent clean build in every history. Both compilers rejected the type error with E0308, reproduced the repaired binary, and passed both selected libtests and both native renderer probes. Cold used 0.032% more instructions and unchanged used 0.013% more at the median. The unchanged command performed its normal Wild relink. The candidate’s median total edited target and build allocation increased by 421,888 bytes over roughly 603 MB. [Independent native replay](https://github.com/astral-experiments/ohm/actions/runs/41444702815)

From this Git checkout, reproduce the table and statistics with Python’s standard library.

```sh
python3 -I -B scripts/ruff-heldout-mono-fold/evidence/41442143564/verify.py
```

The tar preserves the original counter, source, resource, Cargo event, native verdict, physical donor and storage records. `pairs.tsv` gives all six paired instruction counts. `provenance.json` records the six original archive hashes and the independent reader’s three artifact identities. The seventh worker checked the original dependency graphs and work-product tables, rehashed each native body and independently executed the programs before inspecting the scored counters. The six full source archives and 49 MB of deduplicated native products remain hosted separately. [Native products](https://github.com/astral-experiments/ohm/actions/runs/41444702815/artifacts/13142020977)

To repeat the full graph and executable audit, download the six original ZIPs by the artifact IDs in `provenance.json`, leaving their bytes intact. Name them `slot-<slot>-<artifact-id>.zip` in a new directory and extract `github-provenance.json` from this tar into that directory. Run the reader below with a checkout of Ruff at `9c53b5de3aae4b1832eb7ee137647dda2466f888`. It needs `zstd`, GNU `nm`, eight GiB of memory headroom, and fifteen GiB of disk headroom after staging the archives. The original measurement command added `--locked --offline -j2 --message-format=json` to the Cargo command above. It used four fixed physical cores, the normal signed Cargo registry placement and source-built Rust compilers from the recorded factory.

```sh
python3 -I -B scripts/ruff-heldout-mono-fold/independent-reader/reader/verify.py \
  /absolute/path/to/the/six-archives --ruff-source /absolute/path/to/ruff
```
