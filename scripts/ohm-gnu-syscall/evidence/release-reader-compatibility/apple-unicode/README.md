# Shipped and integrated Cargo on an Apple Ruff Unicode build

The release Cargo and the integration both ran zero rustcs and zero native links on the first two unchanged visits and the immediate repeat after a real edit. Each compiled two units and linked once for the edit and for its repair. Each rejected the broken generator with E0425 and Cargo 101. The independent clean reader observed the same generated Unicode changes. The four installations used signed Ohm -20 Rust, native arm64 macOS/Xcode, separate targets and Cargo homes, and either default host or explicit Apple target. Each empty Apple build returned 16 artifacts. The separately enrolled Linux build returned 17. [Apple native originals](https://github.com/astral-experiments/ohm/actions/runs/41108831046) · [Independent Linux evidence](https://github.com/astral-experiments/ohm/tree/b15bd28610642ece8ba0fc900cb38253c5a6099e/scripts/ohm-gnu-syscall/evidence/released-unicode-integration)

The compared Cargos are signed release `2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c` and release integration `fd55a13d0220748794ba3c7c9556ef8ceed8591f`. The latter was built with the signed toolchain and all-static/ohm-defaults, without distribution PGO. This package covers the Unicode control and contains no elapsed comparison.

Fetch the two original ZIP artifacts under a read-only authenticated GitHub account, then run the Python reader offline. It reopens the native Cargo Mach-O and source receipt, 32 unaltered Cargo streams, 32 kernel-exec rosters, 28 real reader verdicts, four failing diagnostics, and generated-file identities. Each ZIP has a fixed SHA-256 in the reader. The write to `observations.json` checks a present copy for exact content.

```sh
GH_AUTO_ACCOUNT=oss gh-auto api --allow-escape-sequences repos/astral-experiments/ohm/actions/artifacts/13002072187/zip > cargo.zip
GH_AUTO_ACCOUNT=oss gh-auto api --allow-escape-sequences repos/astral-experiments/ohm/actions/artifacts/13001882997/zip > unicode.zip
python3 -IB verify.py cargo.zip unicode.zip --output observations.json
sha256sum -c SHA256SUMS
```
