# Security policy

If you believe you have found a vulnerability that is in scope for the project, please contact us as
described in the organization
[Security Policy](https://github.com/astral-sh/.github/blob/main/SECURITY.md).

Ohm is an experimental, development-only alternative Rust toolchain. Its backported and
forward-ported optimizations, including proc-macro caching explicitly labeled potentially unsound by
Rust, can produce stale or incorrect build output. Never use Ohm for production builds, releases,
CI correctness validation, or final test results; the normal Rust toolchain must remain
authoritative.
