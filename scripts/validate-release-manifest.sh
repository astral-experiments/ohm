#!/usr/bin/env bash
set -euo pipefail

require_pinned=false
if [[ "${1:-}" == "--require-pinned" ]]; then
  require_pinned=true
  shift
fi

manifest="${1:-toolchains/1.98.0/3.json}"
if [[ $# -gt 1 ]]; then
  echo "usage: validate-release-manifest.sh [--require-pinned] [MANIFEST]" >&2
  exit 2
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required to validate $manifest" >&2
  exit 1
fi

if [[ ! -f "$manifest" ]]; then
  echo "release manifest does not exist: $manifest" >&2
  exit 1
fi

check_jsonschema_version="0.37.4"
manifest_directory="$(cd -- "$(dirname -- "$manifest")" && pwd)"
schema="$manifest_directory/../manifest.schema.json"

if [[ ! -f "$schema" ]]; then
  echo "release manifest schema does not exist: $schema" >&2
  exit 1
fi

if command -v check-jsonschema >/dev/null 2>&1; then
  installed_version="$(check-jsonschema --version)"
  if [[ "$installed_version" != "check-jsonschema, version $check_jsonschema_version" ]]; then
    echo "check-jsonschema $check_jsonschema_version is required, found: $installed_version" >&2
    exit 1
  fi
  check-jsonschema --schemafile "$schema" "$manifest"
elif command -v uvx >/dev/null 2>&1; then
  uvx --from "check-jsonschema==$check_jsonschema_version" \
    check-jsonschema --schemafile "$schema" "$manifest"
else
  echo "check-jsonschema $check_jsonschema_version or uvx is required" >&2
  exit 1
fi

jq -e '
  type == "object" and
  .["$schema"] == "../manifest.schema.json" and
  .schema_version == 1 and
  (.status == "draft" or .status == "pinned") and
  (.release.upstream_rust_version | type == "string" and test("^[0-9]+\\.[0-9]+\\.[0-9]+$")) and
  (.release.ohm_revision | type == "number" and . >= 1 and floor == .) and
  (.release.toolchain_name | type == "string") and
  .sources.rust.repository == "https://github.com/astral-sh/ohm-rust" and
  (.sources.rust.revision | type == "string" and test("^[0-9a-f]{40}$")) and
  .sources.cargo.repository == "https://github.com/astral-sh/ohm-cargo" and
  (.sources.cargo.revision | type == "string" and test("^[0-9a-f]{40}$")) and
  .sources.clippy.repository == "https://github.com/astral-sh/ohm-rust-clippy" and
  (.sources.clippy.revision | type == "string" and test("^[0-9a-f]{40}$")) and
  (
    .sources.rustfmt == null or
    (
      .sources.rustfmt.repository == "https://github.com/astral-sh/ohm-rustfmt" and
      (.sources.rustfmt.revision | type == "string" and test("^[0-9a-f]{40}$"))
    )
  )
' "$manifest" >/dev/null

status="$(jq -er '.status' "$manifest")"
rust_version="$(jq -er '.release.upstream_rust_version' "$manifest")"
ohm_revision="$(jq -er '.release.ohm_revision' "$manifest")"
toolchain_name="$(jq -er '.release.toolchain_name' "$manifest")"
rust_revision="$(jq -er '.sources.rust.revision' "$manifest")"
cargo_revision="$(jq -er '.sources.cargo.revision' "$manifest")"
clippy_revision="$(jq -er '.sources.clippy.revision' "$manifest")"
rustfmt_revision="$(jq -r '.sources.rustfmt.revision // empty' "$manifest")"
zero_revision="0000000000000000000000000000000000000000"
expected_toolchain_name="ohm-$rust_version-$ohm_revision"
path_rust_version="$(basename -- "$(dirname -- "$manifest")")"
path_revision="$(basename -- "$manifest" .json)"

if [[ "$toolchain_name" != "$expected_toolchain_name" ]]; then
  echo "toolchain name $toolchain_name does not match $expected_toolchain_name" >&2
  exit 1
fi

if [[ "$path_rust_version" != "$rust_version" || "$path_revision" != "$ohm_revision" ]]; then
  echo "$manifest does not match release $rust_version revision $ohm_revision" >&2
  exit 1
fi

if [[ "$status" == "draft" ]]; then
  if [[ "$rust_revision" != "$zero_revision" || "$cargo_revision" != "$zero_revision" ||
    "$clippy_revision" != "$zero_revision" ||
    ( -n "$rustfmt_revision" && "$rustfmt_revision" != "$zero_revision" ) ]]; then
    echo "a draft manifest must use zero source revisions" >&2
    exit 1
  fi
elif [[ "$rust_revision" == "$zero_revision" || "$cargo_revision" == "$zero_revision" ||
  "$clippy_revision" == "$zero_revision" ||
  ( -n "$rustfmt_revision" && "$rustfmt_revision" == "$zero_revision" ) ]]; then
  echo "a pinned manifest cannot use zero source revisions" >&2
  exit 1
fi

if $require_pinned && [[ "$status" != "pinned" ]]; then
  echo "release manifest is still a draft" >&2
  exit 1
fi

echo "validated $status release manifest for $toolchain_name"
