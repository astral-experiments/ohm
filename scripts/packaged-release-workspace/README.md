# Release package workspace census

This structural study uses the actual published -20 and -21 tarballs, not a
source-built stand-in. The package IDs, file sizes, checksums, source
provenance, installed native tools and actual macOS loaded compiler driver are
verified. It scores no times.

The Apple arm repeats the 83-program enrollment from private packaging commit
83a420aa3a65343960d998f4f3b8421c95b7f790. The public Ruff edit is
2d253467b5153f82d26c51d49eb8d4156f1768bf →
aa9a1ff88aa83b3f01360ef5b3cb04b2be187206, with precisely the two original
ty_server files. Use cargo +ohm test --workspace --no-run --locked --offline
-j4 --message-format=json, with CI/TF_BUILD and experimental overrides absent.
Each release uses fresh target and shared roots, independent empty old and new
references, cold old, unchanged old, real edit, first and second unchanged,
a real E0425, and repair. Every original returned program is stored by complete
content under its own true Xcode linker provenance. The new test is absent in
old and present in new; it and the prior existing test produce genuine native
test verdicts. The optional full-CGU proof, original 83 complete binaries and
same-release comparison are unchanged. The two different released compilers
and sysroots may emit different output, so cross-release clean hashes are
recorded separately. Unknown original bytes or native ownership fail their
gate. The independent reopener reads the signed Xcode linker and physical rustc
PIDs, all held linker response files, the original Cargo JSON, every full
Mach-O, and the reported native e2e verdicts. A separate room of at least
65 GiB is required for every clean Apple installation.

The preceding historical Apple #293 full-workspace link set is retained in
previous-apple-83.json. The distinct October Linux 50-target source, commit
reversal and Wild evidence require their own enrollment.

    python3 -IB scripts/packaged-release-workspace/apple_reopen.py archived-original.zip
