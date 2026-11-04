"""Keep the authenticated single-boot receiver fixed while counterbalancing its role order."""
import hashlib
import json
import os
from pathlib import Path
import types

HERE = Path(__file__).resolve().parent
plan_file = HERE / 'six-plan.json'
plan = json.loads(plan_file.read_bytes())
slot = int(os.environ['BOOT_SLOT'])
assert str(slot) == os.environ['BOOT_SLOT'] and 0 <= slot < 6
assert plan['orders'] == ['PC', 'CP', 'CP', 'PC', 'PC', 'CP']
assert os.environ['GITHUB_REF_NAME'] == 'charlie/qa-ruff-cli-help-norun-six-stage2-20261104'
src = HERE / 'pilot.py'
original = src.read_bytes()
assert hashlib.sha256(original).hexdigest() == plan['receiver_sha256'] == 'a23ace3fd48a180dd28643ba43d88a2a9e29b47f5c3fc7dd2598d9d363b708e5'
assert hashlib.sha256((HERE / 'registered.json').read_bytes()).hexdigest() == plan['eligibility_sha256']
assert hashlib.sha256((HERE.parent / 'release-transports.json').read_bytes()).hexdigest() == plan['trained_sdk_registration']
# The executed phase, installation, native oracles, prices, and refusal code remain byte-for-byte original.
source = original.decode()
for old, new in [("enumerate('PC')", 'enumerate(ORDER)'), ("'order':'PC'", "'order':ORDER")]:
    assert source.count(old) == 1
    source = source.replace(old, new)
actor = types.ModuleType('frozen_norun_pilot')
actor.__file__ = str(src)
exec(compile(source, str(src), 'exec'), actor.__dict__)
actor.REF = os.environ['GITHUB_REF_NAME']
actor.ORDER = plan['orders'][slot]
actor.registered = actor.registered | {'order': actor.ORDER, 'confirmation_slot': slot}
if __name__ == '__main__':
    try:
        actor.main()
    finally:
        if actor.OUT.is_dir():
            actor.b.put(actor.OUT / 'confirmation.json', {'slot': slot, 'order': actor.ORDER, 'plan': plan,
                         'plan_sha256': hashlib.sha256(plan_file.read_bytes()).hexdigest(), 'pilot_excluded': True})
