# Repeat the private Cargo GC mount replacement with a source-qualified binary

Use an x86_64 Ubuntu worker with sudo, real ext4, rustup, strace, and the signed -21 SDK. Check out this QA protocol in protocol/, including scripts/private-gc-overlay and scripts/gc-mount-evidence. The worker must have read access to its packaging repository's Actions artifacts.

Register the producer's original source, product, workflow and Actions archive before probing. The registration JSON needs source, tree, inventory, cargo_sha256, build_sha256, workflow_sha, artifact_id, workflow_run, archive_size and archive_sha256. Supply numeric IDs and size and lowercase hashes. The original ZIP must have root-level cargo and build.json. The build receipt has qa, candidate, compiled, delivered and tree.{commit,tree,mode_path_sha256_inventory}. The fixed source plus any independent patches must match the registered tree. The test runs the archived executable directly.

On the hosted worker, set GH_TOKEN to its read-only workflow token and run

    set -euo pipefail
    id=$(jq -r .artifact_id registration.json)
    gh api "repos/astral-experiments/ohm/actions/artifacts/$id" > artifact-metadata.json
    gh api "repos/astral-experiments/ohm/actions/artifacts/$id/zip" > product.zip
    python3 -IB protocol/scripts/private-gc-overlay/receive_stack.py registration.json artifact-metadata.json product.zip "$RUNNER_TEMP/owned/sdk-21" "$RUNNER_TEMP/owned/actual-graft"

Both initially absent test directories are separate. The receiver checks the authenticated size/hash, run, workflow revision, repository IDs, Cargo build receipt and source-stamped real cargo -Vv. Each native Cargo enrollment and trace runs without root in an isolated mount namespace. A privileged observer only moves and attaches its own fixture inside that namespace. The native and forced-ENOSYS results are actual-graft/{stack,stack-enosys}/packet/fixed/reattached-result.json, with the original stdout/stderr, physical Cargo/rustc/Wild, trace and descriptor evidence alongside. A passing result requires a preserved inode/payload and nlink=1, no payload unlink, a rejected crossing in the actual resolver and Cargo exit 0. The ENOSYS test also requires real mount-ID opens after the rejected operation.
