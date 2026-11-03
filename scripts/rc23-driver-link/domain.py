"""Compare actual Rust v0 identities across different complete compiler-version domains."""
import gzip
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import gate as g
import identity
def rows_hash(rows):
    return hashlib.sha256((json.dumps(rows,separators=(",",":"))+"\n").encode()).hexdigest()
def resolve(signed,current,rustc,tmp):
    exe=identity.build(rustc,g.HERE/"rustc-demangle-0.1.28.crate",tmp)
    left=identity.index((r[0] for r in signed["symbols"]),exe); right=identity.index((r[0] for r in current["symbols"]),exe)
    matches=identity.join(left,right); reverse=identity.join(right,left)
    assert len(matches)==len(reverse) and all(reverse[v]==k for k,v in matches.items())
    pools=g.read(g.HERE/"probes.json");registered={};actual={};absence={}
    for group,names in pools.items():
        registered[group]={n:matches[n] for n in names if n in matches}
        actual[group]=list(registered[group].values());absence[group]=[n for n in names if n not in matches]
        assert actual[group] and set(registered[group])|set(absence[group])==set(names)
    record={"upstream_parser_archive":identity.CRATE,"upstream_parser_source":identity.SOURCE,"parser_binary":identity.sha(exe),"signed_census":rows_hash(signed),"actual_census":rows_hash(current),"symbols_in_joint_unique_map":len(matches),
            "signed_v0_names":len(left[0]),"actual_v0_names":len(right[0]),"ambiguous_signed_crates":sorted(k for k,v in left[2].items() if len(v)>1),"ambiguous_actual_crates":sorted(k for k,v in right[2].items() if len(v)>1),"enrolled":registered,"unmatched_or_ambiguous":absence}
    return actual,record
