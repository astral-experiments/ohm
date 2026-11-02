"""Rebuild the six-pair statistics and match each original meter record byte for byte."""
import hashlib
import json
from pathlib import Path
import sys
import zlib

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]))
import durable
import evidence
import packets as p

def main():
    path=HERE/"paired-clocks.json"
    p.need(p.digest(path)=="cfb8446515573eea317960e93ef3526262e5b04e28938e4db67a36dac667933c","different archived clock packet")
    q=p.load(path); primary=durable.verify(q)
    named=p.load(HERE/"named-rosters.json"); ranges=p.load(HERE/"original-member-hashes.json")
    p.need(len(ranges)==6 and len({r["rank"] for r in ranges})==6,"different source range cohort")
    keys="start stop user_us system_us instructions enabled running event_errno code".split()
    total=0
    for r,s in zip(q["ranks"],ranges,strict=True):
        p.need(r["rank"]==s["rank"] and r["artifact"]==s["archive"],"different source archive")
        for arm in "PC":
            body=r["arms"][arm]
            p.need(s["members"][f"0-{arm}/objects.json"]["sha256"]==body["objects_sha256"] and
                   evidence.canonical(named[arm])==body["named_roster_sha256"] and
                   {owner:len(groups["donor"]) for owner,groups in named[arm].items()}==body["donors"],
                   "different source native ledger or per-name donor roster")
            for phase,c in body["clock"].items():
                raw=(json.dumps({k:c[k] for k in keys},separators=(",",":"))+"\n").encode()
                src=s["members"][f"0-{arm}/{phase}/clock.json"]
                p.need((len(raw),hashlib.sha256(raw).hexdigest(),f"{zlib.crc32(raw):08x}")==(
                       src["length"],src["sha256"],src["crc32"]),"different original hardware clock bytes")
                total+=1
    p.need(total==36 and p.digest(HERE/"compiletest-accepted.json")==
           "ab5bcfe33d9ed369665d52345da99021cd986aeef85725a3bbee0e4c6b6c4cac","different test evidence")
    print(f"Matched {total} original hardware records, 12 native ledgers and six independent boots.")
    for name in ("A","B","unchanged"):
        x=q["whole_cargo"][name];ci=x["inference"]["median_interval"]
        print(f"{name}: {x['median']['percent']:.6f}% [{ci['lower']['percent']:.6f}, {ci['upper']['percent']:.6f}], two-sided p={x['inference']['two_sided_exact_sign_p']}")

if __name__=="__main__":
    main()
