# ThinLTO backend caching

The ThinLTO cache stack ([compiler #164](https://github.com/astral-sh/ohm-rust/pull/164), [Cargo #142](https://github.com/astral-sh/ohm-cargo/pull/142)) enables automatic reuse of optimized native objects in supported Ohm builds. This is an upcoming toolchain change; Ohm 1.99.0-2 does not include it.

Cargo stores the cache in `<build-dir>/.ohm-thinlto-cache`. `CARGO_BUILD_BUILD_DIR` selects the build directory; without a separate build directory, the cache lives under the target directory. Worktrees that use the same build directory share the storage budget. Compiler and invocation identities still determine which entries can be reused.

No optimization settings change. A build already using ThinLTO can reuse a backend object when its bitcode, compiler, options, target, and LLVM import/export/resolution key match. LLVM still performs whole-program analysis, and changed units still run the normal backend. Fat LTO stays fat LTO.

The current implementation supports native object output on Linux without frontend incremental compilation, including explicit ThinLTO and implicit local ThinLTO in optimized builds. Cargo skips compiler wrappers and older compilers that do not support the cache. The compiler also skips hashless bitcode inputs, modules with inline or global assembly, PGO and instrumentation, custom backends and passes, native CPU detection, split debug information, optimization remarks, and requests for intermediate outputs. Unsupported configurations use the ordinary backend.

## Storage and eviction

After a build finishes, including a failed build, Cargo prunes the managed cache to **2 GiB or 100,000 objects**, whichever limit is reached first. It evicts the least recently used entries first and removes entries unused for **30 days**. The limits cover all compiler and invocation namespaces within that build directory. Concurrent builds can temporarily exceed the limits; pruning never waits for another pruner.

Successful cache hits refresh an entry's modification time. Cache writes are atomic, and missing, unreadable, corrupt, or concurrently evicted entries fall back to normal compilation. Cache failures do not fail the build. Eviction affects only cached objects, leaving Cargo's required build artifacts intact.

## Opt out

Disable only automatic ThinLTO caching:

```console
cargo +ohm -Zohm-thinlto-cache=no build --release
```

Or use the equivalent Cargo configuration:

```toml
[unstable]
ohm-thinlto-cache = false
```

`-Zohm-defaults=no` also disables automatic caching. An explicit rustc `-Zthinlto-cache=PATH` takes precedence over Cargo's directory selection; the owner of that explicit directory is responsible for its eviction policy.

## Focused validation

With a toolchain containing the compiler and Cargo changes, run:

```console
python3 scripts/smoke-test-thinlto-cache.py
```

The smoke test checks automatic population, warm hits, identical cold/warm/opt-out executables, both opt-outs, managed eviction and expiry, and preservation of fat LTO. Release smoke tests also run it for Linux toolchains whose Cargo advertises the new option. `--fallback-rustc /path/to/older/ohm/bin/rustc` additionally checks compatibility with an older Ohm compiler. Compiler regressions cover changed imported code, corrupted objects, unsupported output modes, hashless bitcode, and assembly file inputs. Cargo regressions cover eviction across namespaces, expiry, opt-outs, argument overrides, lock contention, and symlinks.

Earlier prototype measurements found a 3.31 s to 0.93 s improvement on a smaller dependency-heavy probe, 26.41 s to 25.83 s on Ruff, and 294.06 s to 283.01 s on uv. The Ruff and uv results are preliminary, and uv had only one pair. Those comparisons held ThinLTO optimization settings fixed and used the same experimental compiler with upstream LLVM 23.1.1 in both arms; they are not measurements of a distributed Ohm release or of this final integration.
