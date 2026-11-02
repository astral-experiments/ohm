# Signed Ohm −22 metadata after uv #22958

After uv added `MetadataOutputVersion`, ordinary `cargo check -p uv-client --locked --offline -j8` ran rustc for `uv_configuration` and `uv_client`. I repeated the edit from two independently populated incremental histories using the signed Linux x86-64 Ohm −22 release. Each warm build and independent clean build passed the linked behavior check and produced the expected Cargo units and diagnostics. [Landed uv edit](https://github.com/astral-sh/uv/pull/22958) · [Signed Ohm release](https://github.com/astral-experiments/ohm/releases/tag/ohm-1.99.0-22)

In both histories, the public fingerprint of `uv_client` was `86b91d18cf9d9766036dbeab56d30586` after the incremental edit and `6073d32f197ad3f221c0f2bb85b31698` after the clean rebuild. The other 422 public sidecars agreed. The original compiler metadata contains the same 6,292 definition identities and 2,564 changed per-definition fingerprints. The evaluated-allocation record count also differs, at 548 warm and 547 clean. This comparison failed its registered correctness check before any performance measurement.

The archive contains both raw terminal metadata files from each history, the four dependency metadata files, actual compiler arguments, native output inventories, signed compiler metadata listings, and a standard-library-only reader. Its SHA-256 is `949ea439088705e0fe590f2c9e7ac7f2bb8a9ea594330a9fba37460c995ad765`.

```sh
tar -xJf ohm-22-uv-22958-cold-identity.tar.xz
cd signed-identity-replay
python3 -ISB verify.py
```
