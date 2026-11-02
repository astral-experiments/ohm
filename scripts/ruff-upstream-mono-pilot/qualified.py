"""Bind the two full native ELF families to their independently validated build directories."""
import hashlib
import json
from pathlib import Path

PROOF = Path(__file__).with_name("qualified-native.json")
SHA256 = "2ce4bd28f729322565ae7140760570ffa3f2668273f06201e66f3b1a41f61043"

def expected():
    data=PROOF.read_bytes()
    if hashlib.sha256(data).hexdigest()!=SHA256:
        raise ValueError("different native family registration")
    return json.loads(data)["refs"]

def accepted(revision, parent, candidate):
    (p, proster), (c, croster) = parent, candidate
    same = {k:v for k,v in p.items() if k!="cli"} == {k:v for k,v in c.items() if k!="cli"}
    return same and proster==croster and {"P":p["cli"]["whole"],"C":c["cli"]["whole"]}==expected()[revision]
