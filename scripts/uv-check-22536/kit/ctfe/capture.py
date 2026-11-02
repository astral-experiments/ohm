"""Offline object transport for the original byte-identical native witness."""
from pathlib import Path
import hashlib,json
HERE=Path(__file__).resolve().parent
def load(path):return json.loads(path.read_bytes())
def object_data(obj):
    kind,oid=obj;assert kind=='blobs'and len(oid)==40 and all(c in '0123456789abcdef'for c in oid)
    data=(HERE/'objects'/oid).read_bytes();assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==oid
    return data
def save(path,data):
    with path.open('xb')as out:out.write(data)
