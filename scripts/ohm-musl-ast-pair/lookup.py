"""Recover one successful source qualification's exact transfer for a separate measurement checkout."""
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
import restore

s=restore.s


def locate(run,head):
    fetch=lambda p:subprocess.check_output(["gh","api",s.API+p])
    doc=lambda p:json.loads(fetch(p))
    r=doc(f"runs/{run}")
    assert (r["head_sha"],r["event"],r["run_attempt"],r["head_branch"],r["status"],r["conclusion"])==(head,"workflow_dispatch",1,restore.q.REF,"completed","success")
    jobs=doc(f"runs/{run}/jobs?per_page=100")["jobs"]
    assert {j["name"] for j in jobs if j["conclusion"]=="success"}=={
        "Build both source SDKs and run the compiler regression","Ordinary Ruff (P)","Ordinary Ruff (C)",
        "Unbundled native provider (private)","Unbundled native provider (shared)"}
    arts=doc(f"runs/{run}/artifacts?per_page=100")["artifacts"]
    ledger,=[a for a in arts if a["name"]=="musl-285-source-records"]
    assert not ledger["expired"] and ledger["workflow_run"]["id"]==run and ledger["workflow_run"]["head_sha"]==head
    buf=fetch(f"artifacts/{ledger['id']}/zip")
    assert "sha256:"+restore.hashlib.sha256(buf).hexdigest()==ledger["digest"]
    with zipfile.ZipFile(io.BytesIO(buf)) as z:
        path,=[p for p in z.namelist() if p.endswith("/transfer.json")]
        u=json.loads(z.read(path))
    transfer,=[a for a in arts if a["id"]==u["transfer_id"] and a["name"]=="musl-285-source-transfer"]
    assert (u["run"],u["head"],u["transfer_digest"],transfer["expired"])==(run,head,transfer["digest"].split(":")[1],False)
    assert len(u["identity_sha256"])==64
    return {"SOURCE_RUN":str(run),"SOURCE_HEAD":head,"TRANSFER_ID":str(transfer["id"]),
            "TRANSFER_DIGEST":u["transfer_digest"],"TRANSFER_SEAL":u["identity_sha256"]}


if __name__=="__main__":
    for k,v in locate(int(sys.argv[1]),sys.argv[2]).items():print(f"{k}={v}")
