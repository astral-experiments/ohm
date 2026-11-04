# Delimited literal lexer controls

The candidate scans comma-separated short decimal and one-hash raw string literals before emitting their ordinary Rust tokens. The comparison uses the actual Rust parser and procedural macro bridge. The seed, source identities, 287 generated inputs and bytewise acceptance rule were fixed before the candidate observations. The source factory enrollment records both the bootstrap and the single compiler delta.

Copy this directory to a fresh writable path. Supply the rustup homes of the verified parent and candidate kits.

```sh
python3 -IB cases.py
python3 -IB run.py c8 "$C8_RUSTUP"
python3 -IB run.py c9 "$C9_RUSTUP"
```

The baseline produced 187 successes and 100 failures across four Rust editions. The token observer writes each literal or identifier's spelling, each punctuation's joint spacing, group delimiters, source snippets, byte offsets and line/column coordinates. The reader compares complete token streams, stderr, stdout and exit statuses. Required positive and negative typed Rust inputs independently check warnings, errors and parser fallback.

The separate historical Ruff RNG measurement uses the original checkout and lock at each end of #29261. Both ordinary Cargo and an independent execution under Callgrind run from the same visible checkout, Rust toolchain path, and private target/build paths, without a compiler wrapper. Its owner price requires the exact kernel-observed compiler argv and the complete normal emitted metadata, generated table bytes, settled and independently cold check. Independently linked clients check every available Unicode name and alias on the actual native build.

The standalone experimental cutoff is at least 6% fewer instructions in either complete compiler on a genuine Ruff edit, relative to the immediately preceding parser candidate C8. A distinct comparison asks whether the cumulative C7 to C9 compiler on the RNG edit reaches 6% on its own direct measurement. The earlier wrapper-based RNG observation and the original 1.891× trained study have separate baselines and denominators. The two retained workflows will report their native oracles and every refused comparison.
