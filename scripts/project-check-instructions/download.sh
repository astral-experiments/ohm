#!/usr/bin/env bash
set -euo pipefail
run=$1
name=$2
member=$3
output=$4
[[ "$run" =~ ^[0-9]+$ ]]
url="$GITHUB_API_URL/repos/$GITHUB_REPOSITORY/actions"
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
download() {
  curl -fsSL --connect-timeout 10 --speed-time 15 --speed-limit 8192 \
    --max-time 360 --retry 3 --retry-all-errors \
    -H "Authorization: Bearer $GITHUB_TOKEN" "$@"
}
info=$(download "$url/runs/$run/artifacts?name=$name")
id=$(jq -er '.artifacts[0].id' <<< "$info")
digest=$(jq -er '.artifacts[0].digest' <<< "$info")
[[ "$digest" =~ ^sha256:[a-f0-9]{64}$ ]]
download "$url/artifacts/$id/zip" -o "$tmp"
echo "${digest#sha256:}  $tmp" | sha256sum -c -
mkdir -p "$(dirname "$output")"
unzip -p "$tmp" "$member" > "$output"
test -s "$output"
echo "$name $run $digest"

