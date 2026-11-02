"""Compare emitted rooted DefKeys when the two genuine compiler versions generate different numeric crate IDs."""
import hashlib,json
def digest(v):
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def shape(header,definitions):
    resolved={};visiting=set()
    def canonical(k):
        if k in resolved:return resolved[k]
        assert k not in visiting and k in definitions,('cyclic or missing local definition',k)
        visiting.add(k);raw,parent,kind,symbol,disambiguator=definitions[k]
        assert (parent is None)==(kind=='CrateRoot') and type(disambiguator)is int and 0<=disambiguator<=2**32-1
        parent_key=canonical(parent) if parent is not None else None
        value=digest([parent_key,kind,symbol,disambiguator]);resolved[k]=value;visiting.remove(k);return value
    rows=[];roots=0
    for k,(raw,parent,*_)in definitions.items():
        roots+=parent is None
        rows.append([canonical(k),any(bytes.fromhex(raw))])
    assert roots==1 and len(rows)==len({v[0]for v in rows})==header['definition_count']
    return {'crate':header['crate_name'],'target':header['target'],'definitions':len(rows),'rooted_keys_and_public_presence_sha256':digest(sorted(rows))}
