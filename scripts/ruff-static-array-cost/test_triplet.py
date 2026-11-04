"""Exercise registration boundaries with synthetic counters and typed literals, without profiling."""
import copy
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
import triplet

def cohort(orders):
    out = {}
    for i,(block,order) in enumerate(orders.items()):
        rows, stores = {},{}
        for arm,amount in {"F5":8_000_000_001,"C5":5_500_000_000,"C7":4_000_000_000}.items():
            rows[arm] = {mode:{field:amount if field in ("target_rustc","whole_edit") else 2_000_000_000
                               for field in triplet.FIELDS} for mode in triplet.MODES}
            stores[arm] = {mode:{phase:{"logical":50_000_000,"allocated":51_000_000}
                        for phase in ("ordinary-edit","unchanged","empty-new")}for mode in triplet.MODES}
        out[block] = {"order":order,"boot":f"test-{i}","results":rows,"storage":stores}
    return out

pilot = cohort(triplet.PILOTS)
assert triplet.judge(pilot)["admit_six"] and not triplet.judge(pilot)["confirmed_twofold"]
bad = copy.deepcopy(pilot)
bad["H2"]["results"]["C7"]["check"]["whole_edit"] = bad["H2"]["results"]["C5"]["check"]["whole_edit"]
assert not triplet.judge(bad)["admit_six"]
bad = copy.deepcopy(pilot)
bad["H1"]["results"]["C7"]["check"]["target_rustc"] = 5_000_000_001
assert not triplet.judge(bad)["admit_six"]
six = cohort(triplet.CONFIRM)
assert triplet.judge(six)["confirmed_material"] and triplet.judge(six)["confirmed_twofold"]
six["B1"]["results"]["F5"]["check"]["target_rustc"] = 8_000_000_000
ans = triplet.judge(six)
assert ans["confirmed_material"] and not ans["confirmed_twofold"] and ans["twofold_exact_two_sided_sign_p"] is None
for r in six.values():
    r["results"]["C7"]["check"]["unchanged"] = 2_100_000_000
assert not triplet.judge(six)["vetoes"]  # exactly 5%
for r in six.values():
    r["results"]["C7"]["check"]["unchanged"] += 1
assert not triplet.judge(six)["confirmed_material"]
six = cohort(triplet.CONFIRM)
for r in six.values():
    r["storage"]["C7"]["build"]["ordinary-edit"]["allocated"] += 1024*1024+1
assert not triplet.judge(six)["confirmed_material"]
six = cohort(triplet.CONFIRM)
six["B2"]["boot"] = six["B1"]["boot"]
try: triplet.judge(six)
except AssertionError: pass
else: raise AssertionError("reused boot accepted")

def literal(tail_pair=b"(65535,0)", tail_char=b"'x'", earlier=1023):
    return (triplet.PHF_HEADERS[0].encode()+b"(1,2),"*earlier+tail_pair+b",];\n"+
            triplet.PHF_HEADERS[1].encode()+b"'x',"*earlier+tail_char+b",];")
actual=triplet.census(literal(tail_char=br"'\u{10ffff}'"))
assert actual["u16_pairs"]["rows"] == actual["chars"]["rows"] == 1024
for fail in (literal(tail_pair=b"(65536,0)"),literal(tail_char=br"'\u{d800}'"),
             literal(tail_char=b"65u32"),literal(earlier=1022),literal(tail_pair=b"(1 + 0,2)")):
    try: triplet.census(fail)
    except ValueError: pass
    else: raise AssertionError("invalid PHF input accepted")
with tempfile.TemporaryDirectory()as tmp:
    root=Path(tmp);a=root/"target";b=root/"shared";a.mkdir();b.mkdir()
    (a/"one").write_bytes(b"abc");(b/"two").hardlink_to(a/"one");(b/"symlink").symlink_to(a/"one")
    st=triplet.storage({"target":a,"shared":b})
    assert st["files"]==1 and st["logical"]==3 and st["allocated"]==(a/"one").stat().st_blocks*512
print("Passed gates for exact 2×, cumulative/incremental/material separation, two whole-check comparisons, common/storage veto, distinct boots, typed rows and hardlink accounting.")
