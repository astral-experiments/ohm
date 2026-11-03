"""Recover crate hashes and the exact historical module and field scopes from original bytes."""
import gzip
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import scope_rdr

HERE=Path(__file__).resolve().parent
schema_bytes=(HERE/'schema.json.gz').read_bytes()
assert hashlib.sha256(schema_bytes).hexdigest()=='236f4a0f399c405ddde4b5112d5b75983916b6ce5a3ee8056274c2dcc9047c5e'
schema_raw=gzip.decompress(schema_bytes)
assert hashlib.sha256(schema_raw).hexdigest()=='c0858b0f370a31b9693064e8feab73ecbcd7ac5079a849d9bb67f212cabf11e8'
SCHEMA=json.loads(schema_raw)
VERSION='rustc 1.99.0-dev (Ohm metadata 3)'
MODULE='rules::pylint::helpers'
VISITOR=MODULE+'::SequenceIndexVisitor'
FIELDS={'sequence_name','index_name','value_name','accesses','modified'}
TBL=('type_of','mut_restriction','optimized_mir','mir_for_ctfe')


def decode(raw,owner,edition):
    typed={} if owner=='ruff_linter' else None
    root,defs,rows,_,deps=scope_rdr.decode(raw,SCHEMA['symbols'],SCHEMA['tables'],owner,VERSION,typed=typed,selected_tables=TBL if typed is not None else (),edition=edition)
    result=dict(header=root,edition=edition,required=deps,definitions=len(defs),published=len(rows))
    if typed is None:return result
    ids=typed['path_by_index'];lookup={val[1]:idx for idx,val in ids.items()}
    tables=typed['selected_tables']
    rdr=scope_rdr.Reader(raw,SCHEMA['symbols'])
    def address(which,idx):return int.from_bytes(tables[which][idx],'little')
    def local_def():
        assert rdr.var()==0
        key=rdr.take(8).hex();assert key in defs
        return key
    module_key=ids[lookup[MODULE]][0];module_scope=typed['visibility'][module_key]
    assert typed['kinds'][module_key]==1 and module_scope in defs
    i=lookup[VISITOR];struct=ids[i][0];rdr.pos=address('type_of',i)
    tag=rdr.var()
    if tag>=128:rdr.pos=tag-128;tag=rdr.var()
    assert tag==5 and local_def()==struct and rdr.var()==1 and local_def()==struct
    ctor=rdr.var();assert ctor in (0,1)
    if ctor:assert rdr.var() in (0,1);local_def()
    assert rdr.symbol()=='SequenceIndexVisitor' and rdr.var()==1 and rdr.var()==0
    n=rdr.var();assert n==5
    decoded={}
    for _ in range(n):
        key=local_def();name=rdr.symbol();assert defs[key][0]==VISITOR+'::'+name and name not in decoded
        start=rdr.pos;assert rdr.var()==1 and local_def()==module_key
        assert typed['visibility'][key]==module_key
        fieldscope=raw[start:rdr.pos].hex(); mutation=rdr.var(); assert mutation==raw[address('mut_restriction',lookup[defs[key][0]])]==0
        assert rdr.var() in (0,1); has_default=rdr.var();assert has_default in (0,1)
        if has_default:local_def()
        decoded[name]=dict(key=key,scope=module_key,encoded=fieldscope,published=rows.get(key))
    assert set(decoded)==FIELDS
    funcs={}
    for name in (MODULE+'::is_dunder_operator_method',MODULE+'::is_known_dunder_method','rules::flake8_self::rules::private_member_access::is_dunder_operator','rules::flake8_self::rules::private_member_access::private_member_access'):
        if name not in lookup:continue
        ix=lookup[name];key=ids[ix][0]
        funcs[name]=dict(key=key,published=rows.get(key),optimised=ix in tables['optimized_mir'],ctfe=ix in tables['mir_for_ctfe'])
    result['witness']=dict(module=module_key,scope=defs[module_scope][0],public_row=rows.get(module_key),visitor=struct,fields=decoded,functions=funcs)
    return result
