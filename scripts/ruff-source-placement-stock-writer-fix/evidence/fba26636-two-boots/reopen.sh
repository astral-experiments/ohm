#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
sha256sum --check --strict --quiet SHA256SUMS
(
  cd ../fba26636-native
  sha256sum --check --strict --quiet SHA256SUMS
  python3 -IB review_compact.py ../.. . native 41556515852 fb2ea0a339a9dcef0011b2f1828b5b7c7531795d
  python3 -IB test_compact.py ../.. .
)
python3 -IB ../fba26636-native/review_compact.py ../.. . score 41561666391 a359a2db1d9df7bc147e1506bf10ec90123f1417
python3 -IB ../fba26636-native/test_compact.py ../.. .
python3 -IB report_score.py recomputed.json | cmp -s - absolute-prices.md
python3 -IB fold_gate.py recomputed.json prespecified-fold-gate.json | cmp -s - fold-result.json
echo "Reopened both native histories, both genuine migrations, 36 full-workflow counts, both tables and the no-fold decision."
