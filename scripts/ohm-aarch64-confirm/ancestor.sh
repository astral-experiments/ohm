#!/bin/bash
set -euo pipefail
kit=$1
mkdir -p "$kit/inputs" "$kit/receipts"
cd "$kit/inputs"
gh api "repos/$GITHUB_REPOSITORY/actions/runs/41057968152" --jq '[.head_sha,.status,.conclusion]|@tsv' > workflow
test "$(cat workflow)" = "$(printf 'c54c565ebbf3116322c61689ba6d793c5f637de0\tcompleted\tsuccess')"
gh api "repos/$GITHUB_REPOSITORY/actions/artifacts/12977632631/zip" > sdk.zip
gh api "repos/$GITHUB_REPOSITORY/actions/artifacts/12977184593/zip" > native.zip
echo 'da327a22d280aca99b74b60b07cb962fe88cacdba2a197960254d1a5c1cd2338  sdk.zip' | sha256sum -c -
echo '44cb09e19e4297460c62fab748a7ba8c49d47bbeadf80d23a83d5134a1c917ee  native.zip' | sha256sum -c -
unzip -qp sdk.zip linux-aarch64-sdk-pair.tar.zst > sdk.tar.zst
unzip -q native.zip -d native
echo d4a58ad69b0b2427f0fa1c4f3a9945783d7f2a9e3a4de9525d97f69db4f2a79b > key
echo 'd4a58ad69b0b2427f0fa1c4f3a9945783d7f2a9e3a4de9525d97f69db4f2a79b  sdk.tar.zst' | sha256sum -c -
QA_ROOT="$kit" python3 -IB "$GITHUB_WORKSPACE/scripts/ohm-aarch64-confirm/study.py" old "$kit/inputs"
