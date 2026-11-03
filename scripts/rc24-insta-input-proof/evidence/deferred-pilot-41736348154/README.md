# Late validation of recorded registry inputs on two independent boots

The genuine Ruff #29604 change adds a 78th `ty_project` test. On the first subsequent unchanged `cargo +ohm test -p ty_project --lib --no-run --locked --offline -j4 --message-format=json`, the Cargo parent compiled `insta` and `ron`. The candidate compiled `ron`. Both ran the real `ty_project` link-only rustc and Wild. These are whole, inherited Linux userspace retired instructions from normal Cargo commands. Separate kernel exec records establish the process roster.

| Whole command | CP parent → candidate | PC parent → candidate |
|---|---:|---:|
| First unchanged test build | 53,005,193,525 → 12,667,395,288 (4.18438×) | 53,002,768,217 → 12,666,167,145 (4.18459×) |
| Genuine edit | 70,930,662,566 → 30,588,844,307 (2.31884×) | 70,927,932,584 → 30,593,573,355 (2.31839×) |
| Unchanged check | 998,029,637 → 991,878,054 | 997,840,341 → 991,717,544 |
| Unchanged build | 461,798,303 → 460,429,562 | 461,918,206 → 460,242,732 |
| Empty initial test build | 1,809,819,156,069 → 1,809,990,148,426 | 1,810,412,738,519 → 1,809,388,023,325 |

The same 144 translated dep-info files occupied 248,440 logical bytes on the parent and 326,390 on the candidate (+77,950 B). The candidate stores direct registry source checksums and opens those files for validation after a prerequisite has been rebuilt. Cargo's ordinary initial check retains its existing handling of registry sources. The earlier broad prototype also hashed them on ordinary common no-ops and hit its regression gate. [Original broad trial](../broad-pilot-41729274046/README.md).

Both optimized Cargo binaries were freshly built from authenticated sources using the published Linux Ohm `1.99.0-24` rustc, compiler runtime, standard library and Wild. The Cargo parent was `abc70d60a6fd89c10d5f65cf85820d9b78d5affe` and the candidate was `1b44b5d3dc540c491c79bbf47fae8b286e8f797a`. The factory used independent directories for the two all-static release builds. The complete source identity, command and binary SHA-256 are in the three original archives. [Compiler and Cargo source enrollment](../../registration.json), [matched factory](https://github.com/astral-experiments/ohm/actions/runs/41734567724).

Across both roles and boots, the edited, repaired and independently empty native program had the same complete SHA-256. Each positive control executed the new test. Each of the four role/boot histories rejected a same-length, same-inode, same-mtime registry edit twice with E0308. On a separate 11-command migration in one physical install, the original reader wrote 14 bytes containing zero input files and the new reader wrote 2,424 bytes with 22 inputs. The verifier reopens the actual kernel rustcs, native outputs, both errors, registry archive and every stored BLAKE3. The valid registry change produced different executable behavior immediately on upgrade. The invalid attempts preserved that valid executable, and repair matched the independently empty executable.

This unscored pilot admitted a separate six-boot counterbalanced confirmation and a distinct full-default-workspace follow-up. [Pilot run](https://github.com/astral-experiments/ohm/actions/runs/41736348154), [confirmation run](https://github.com/astral-experiments/ohm/actions/runs/41739057338), [full workspace run](https://github.com/astral-experiments/ohm/actions/runs/41739061503).

Reopen the two original hardware ZIPs, the independent migration ZIP and all 48 ordinary counts from this directory. Python and a C compiler suffice. `verified.json` contains each absolute value, cold and second controls, kernel rosters, native hashes and paired decisions.

```sh
python3 -IB ../../price-review.py . --suite ../.. --crate insta-1.48.0.crate --prior-boots prior-boots.json --migration
sha256sum -c SHA256SUMS
```
