"""Replay the #21179 R/S originals using Python 3.11+ and the standard library."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import runpy
import struct
import tarfile
import tempfile
import tomllib
import zipfile

HERE = Path(__file__).resolve().parent
UV_A = "89c102d09fe5532f5f3e0a0dbf5ea557a6bdd1fd"
UV_B = "392e0a0aa39f7f03e2efb688e500ec23a1930d36"
SRC = "crates/uv-resolver/src/lock/mod.rs"
RELEASE = "fc85a2ca6d47711058cd89c790c8e57f1799472e38f0ee0a08b0a51d06c1ee7b"
SDK = "e83f2043db15a49a0d3d1bed105f2f6a8ca140e6c0787bc87c9902c49d2ed7ad"
QA = "4c360c799fda11fe7ee55103a7a7becf20d123ca2a3a7cfed0f8589d0a672a30"
CARGO = "f7cfe387ec3bd7e2e367d80596f379349faa23530194bf7cd7ba80a33adc6dee"
COMMITS = {"R": "d57fd1515986dccecdcece8da85e651bfb4b81f9", "S": "b5bbf6e74cd71de00a5c805d365e93673f248265"}
OUTCOME = {"R": "39154fdb51d9e79ed62ebb429bfe05fa5854ac6c816ac53e8d83a5060046982d", "S": "2db928b9e570a2ee831c8704551b395a4c5d9d72ff76eabf125a88075d674a91"}
LOCK = "d6ffbfa02a5e2382fd78f02c85b6c1604c9c8f304d1d504a1199aa23dd6858b2"
COMMAND = ["/tmp/uv-workflow-search/sdk/bin/cargo", "check", "-p", "uv-resolver", "--locked", "--offline", "-j8"]
LITERALS = {"size", "url", "version", "upload-time", "source", "upload_time", "path", "hash", "name"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def pack(path, cap):
    files, total = {}, 0
    with tarfile.open(path, "r:xz") as t:
        for member in t:
            p = PurePosixPath(member.name)
            total += member.size
            assert total <= cap and member.isfile() and member.name not in files
            assert not p.is_absolute() and ".." not in p.parts and str(p) == member.name
            files[member.name] = t.extractfile(member).read()
    return files


def tree(data):
    result, i = {}, 0
    while i < len(data):
        space = data.index(b" ", i)
        end = data.index(b"\0", space)
        name = data[space + 1:end].decode()
        assert name not in result and end + 21 <= len(data)
        result[name] = (data[i:space].decode(), data[end + 1:end + 21].hex())
        i = end + 21
    return result


def verify_git(raw, j):
    info = j("git/revisions.json")
    for path, content in raw.items():
        if path.startswith("git/") and not path.endswith(".json"):
            _, kind, oid = path.split("/")
            prefix = f"{kind} {len(content)}".encode() + b"\0"
            assert hashlib.sha1(prefix + content).hexdigest() == oid
    for s, rev in (("A", UV_A), ("B", UV_B)):
        item = info[s]
        commit = raw["git/commit/" + rev]
        assert rev == item["id"] and commit.startswith(("tree " + item["root"] + "\n").encode())
        if s == "B":
            assert re.findall(rb"(?m)^parent ([0-9a-f]{40})$",commit) == [UV_A.encode()]
        for path, expected in item["paths"].items():
            oid = item["root"]
            for part in path.split("/"):
                _, oid = tree(raw["git/tree/" + oid])[part]
            assert oid == expected
        src = raw["git/blob/" + item["paths"][SRC]]
        assert re.search(rb"(?m)^struct PackageMetadata\s*\{",src)
        assert src.count(b"PackageMetadata::from_distribution(") == (s == "B")
        assert bool(re.search(rb"(?m)^impl PackageMetadata\s*\{\s*fn from_distribution\(",src)) == (s == "B")
        assert b"fn lock_index_workspace_member" in raw["git/blob/" + item["paths"]["crates/uv/tests/lock/lock.rs"]]
        for k in COMMITS:
            receipt = j(f"{k}/source-{s}.json")
            assert receipt["actual_tree"] == item["root"] and receipt["git_head"] == UV_A
            assert receipt["files"][SRC] == sha(src)
            assert receipt["lock"] == sha(raw["git/blob/" + item["paths"]["Cargo.lock"]])
    assert info["A"]["paths"]["Cargo.lock"] == info["B"]["paths"]["Cargo.lock"]
    # Verify every sibling, including siblings at the root, to rule out another changed file.
    left, right = info["A"]["root"], info["B"]["root"]
    for part in SRC.split("/"):
        a, b = tree(raw["git/tree/" + left]), tree(raw["git/tree/" + right])
        assert a.keys() == b.keys() and {n for n in a if a[n] != b[n]} == {part}
        left, right = a[part][1], b[part][1]


def verify_sdks(raw, j):
    lock = j("authority/split-lock.json")
    official, stock, intake = lock["signed_release"], j("official/actual-linux-sdk.json"), j("official/intake.json")
    assert official["release_id"] == intake["release_id"] == 432227571
    assert official["asset"] == stock["archive"] and official["asset"]["id"] == 704038224
    assert official["sha256"] == RELEASE and sha(raw["official/published-manifest.json"]) == official["manifest_sha256"]
    assert intake["manifest_rust"] == official["rustc"] == COMMITS["R"] and intake["manifest_cargo"] == official["cargo"]
    for name in ("verify.json","verify-asset.json"):
        att = j("official/" + name)
        stmt = att["verificationResult"]["statement"]
        envelope = att["attestation"]["bundle"]
        assert envelope["verificationMaterial"] and envelope["dsseEnvelope"]["signatures"]
        assert sum(x.get("name") == official["asset"]["name"] and x["digest"].get("sha256") == RELEASE for x in stmt["subject"]) == 1
        assert sum(x["digest"].get("sha1") == official["coordinator"] for x in stmt["subject"]) == 1
    assert j("official/native-ctfe.json")["checks"] == {
        "A_differs_from_B":True,"B_warm_equals_cold":False,"C_warm_equals_cold":True,"pointer_switch_changes_public_hash":True}
    builder, origin, run = lock["builders"]["S"], j("producer/originals.json"), j("producer/run.json")
    assert run["id"] == origin["run"] == builder["run"] == 41572266236 and run["conclusion"] == "success"
    assert run["head_sha"] == builder["head"] == "683db047247d11b881bfea1bca34543826a7511d"
    jobs = {v["id"]:v for v in j("producer/jobs.json")["jobs"]}
    assert builder["job"] == 125707756416 and jobs[builder["job"]]["conclusion"] == "success"
    artifacts = {v["id"]:v for v in j("producer/artifacts.json")["artifacts"]}
    for k, ident, digest in (("sdk",13204110687,SDK),("qa",13203896034,QA)):
        v, a = builder[k], artifacts[ident]
        assert v["id"] == ident and v["digest"] == a["digest"] == "sha256:" + digest
        assert v["size_in_bytes"] == a["size_in_bytes"] and v["name"] == a["name"]
        assert a["workflow_run"]["id"] == builder["run"] and a["workflow_run"]["head_sha"] == builder["head"]
    for name, h in origin["api"].items():
        assert sha(raw["producer/" + name]) == h
    assert sha(raw["producer/qa.zip"]) == QA
    with zipfile.ZipFile(io.BytesIO(raw["producer/qa.zip"])) as qa:
        for n in ("source.json","role.json"):
            assert qa.read("capacity/" + n) == raw["producer/sdk/" + n]
    for n,h in builder["sdk_members"].items():
        assert sha(raw["producer/sdk/" + n]) == h
    source, role = j("producer/sdk/source.json"), j("producer/sdk/role.json")
    assert source["source"]["parent"] == COMMITS["R"] and role["source_commit"] == COMMITS["S"]
    changes = source["strict_source"]["template"]["changed_files_sha256"]
    assert {p for p in changes if not p.startswith("tests/")} == {
        "compiler/rustc_incremental/src/persist/file_format.rs","compiler/rustc_middle/src/mir/interpret/mod.rs",
        "compiler/rustc_middle/src/mir/interpret/tests.rs"}
    assert role["bolt_note"] and role["execution_pgo"] and "rdr-public-hash-ctfe-literal-identity" in role["installed_runmake"]
    for k in COMMITS:
        inv, receipt = j(k+"/sdk/sdk-inventory.json"), j(k+"/sdk/registered.json")
        assert inv == lock["raw"][k] and receipt["source"] == lock["sources"][k] and receipt["source"]["commit"] == COMMITS[k]
        assert (receipt["source"]["epoch"],receipt["source"]["metadata_epoch"]) == ((26655 if k=="R" else 43421),3)
        values = {p:row["sha256"] for p,row in inv.items()}
        values["bin/cargo"] = CARGO
        digest = sha(json.dumps(values,sort_keys=True,separators=(",",":")).encode())
        assert len(inv) == receipt["files"] == 142 and digest == receipt["effective_inventory"] == lock["effective_hashes"][k]
        assert receipt["runtime"]["bin/cargo"] == CARGO and all(values[p] == h for p,h in receipt["runtime"].items())
        if k == "R":
            assert all(stock["members"][p] == {"bytes":v["bytes"],"sha256":v["sha256"]} for p,v in inv.items())
        else:
            assert inv == j("producer/sdk/sdk-inventory.json") and receipt["source"]["tree"] == role["source_tree"]
    return lock


def large_archive(role, path, lock):
    assert sha_file(path) == (RELEASE if role=="R" else SDK)
    inventory = lock["raw"][role]
    def contents(file):
        seen = set()
        with tarfile.open(fileobj=file,mode="r|gz") as t:
            for m in t:
                fields = m.name.split("/",2)
                if len(fields) != 3:
                    continue
                _,component,p = fields
                row = inventory.get(p)
                if not row or component != row["component"]:
                    continue
                assert p not in seen and m.isfile() and m.size == row["bytes"] and m.mode & 0o777 == row["mode"]
                assert hashlib.file_digest(t.extractfile(m),"sha256").hexdigest() == row["sha256"]
                seen.add(p)
        assert seen == set(inventory)
    if role == "R":
        with path.open("rb") as f:
            contents(f)
    else:
        b=lock["builders"]["S"]
        with zipfile.ZipFile(path) as z:
            assert set(z.namelist()) == {"ohm.tar.gz", *b["sdk_members"]}
            for n,h in b["sdk_members"].items():
                assert sha(z.read(n)) == h
            with z.open("ohm.tar.gz") as f:
                assert hashlib.file_digest(f,"sha256").hexdigest() == b["archive_sha256"]
            with z.open("ohm.tar.gz") as f:
                contents(f)


def toolkit(records, media, cache):
    spec = json.loads(records["tools/decoder.json"])
    path = HERE/"metadata-kit.tar.xz"
    items = pack(path,8<<20)
    assert sha_file(path) == spec["kit_sha"] and items.keys() == spec["toolkit"].keys()
    for name,data in items.items():
        assert sha(data) == spec["toolkit"][name]
        dest = cache/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(data)
    m = runpy.run_path(str(cache/spec["kit_module"]))
    def read_raw(row):
        raw = media[row[1]]
        assert len(raw) == row[0]
        return raw
    m["check_delta"].__globals__["C"]["raw"] = read_raw
    return m


def verify_role(k, raw, j, media, tools, events):
    def J(n):
        return j(k+"/"+n)
    o, scope = J("outcome.json"), j("authority/scopes.json")[k]
    assert sha(raw[k+"/outcome.json"]) == scope["outcome"] == OUTCOME[k]
    assert J("physical.json")["exit"] == 0 and J("registry.json")["actual_archives"] == 683
    assert (not o["scored_outcomes"] and o["counts"] is None) if k=="R" else o["performance"] is None
    stages = ("cold-A","first-B","fresh-B")
    products = {s:J(s+"/products.json") for s in (*stages,"kernel-B")}
    for s in stages:
        cmd = J(s+"/command.json")
        assert cmd["argv"] == COMMAND and cmd["rc"] == 0 and cmd["cwd"] == "/tmp/uv-workflow-search/uv"
        assert cmd["env"]["RUSTC"] == "/tmp/uv-workflow-search/sdk/bin/rustc"
        assert not set(cmd["env"]) & {"RUSTFLAGS","CARGO_ENCODED_RUSTFLAGS","RUSTC_WRAPPER","RUSTC_WORKSPACE_WRAPPER","RUSTC_BOOTSTRAP"}
    assert products["kernel-B"] == products["first-B"]
    trace_counts = []
    for s in ("unchanged-A","kernel-B","unchanged-B"):
        observed = J(s+"/observed.json")
        d = events(J(s+"/kernel-events.json"))
        assert observed["command"] == d["images"][0]["argv"] == COMMAND and d["exits"][d["root"]] == 0
        rust = [i for i in d["images"] if Path(i["exe"]).name=="rustc" or Path(i["argv"][0]).name=="rustc"]
        assert rust == observed["rows"] and all(d["exits"][i["pid"]] == 0 for i in rust)
        trace_counts.append(len(rust))
        if s == "kernel-B":
            one, = rust
            argv,pid = one["argv"],one["pid"]
            assert argv[argv.index("--crate-name")+1]=="uv_resolver" and argv[argv.index("--crate-type")+1]=="lib"
            assert "crates/uv-resolver/src/lib.rs" in argv and observed["forms"] == {"uv_resolver":argv}
            externs = {v.partition("=")[2] for i,v in enumerate(argv) if i and argv[i-1]=="--extern" and "=" in v}
            assert externs == set(J("actual-B-externs.json")["uv_resolver"]) and len(externs)==62
    assert trace_counts == [0,1,0]
    warm,cold = products["first-B"],products["fresh-B"]
    admit = J("independent-cold.json")
    assert sha(raw[k+"/independent-cold.json"]) == scope["typed_receipt"] == o["typed"]
    sizes = {n:len(v) for n,v in warm.items()}
    assert sizes == admit["counts"] == {"public_sidecars":471,"rmeta":571,"workspace":50}
    assert all(warm[n].keys()==cold[n].keys() for n in sizes)
    assert warm["public_sidecars"]==cold["public_sidecars"] and not admit["sidecar_mismatches"]
    changed_api = [p for p,v in products["cold-A"]["public_sidecars"].items() if cold["public_sidecars"][p]!=v]
    assert len(changed_api)==1 and "lib-uv_resolver.public-api-hash" in changed_api[0]
    differences = {p:[v,cold["rmeta"][p]] for p,v in warm["rmeta"].items() if v!=cold["rmeta"][p]}
    assert differences==admit["different"]
    pairs = {v[0][1]+":"+v[1][1] for v in differences.values()}
    assert pairs == set(admit["records"])
    failures,resolver = {},None
    for pair,v in admit["records"].items():
        delta = v["delta"]
        full = tools["check_delta"](delta["warm"],delta["cold"],v["unit"])
        assert json.loads(json.dumps(full)) == delta
        failed = [n for n,ok in full["checks"].items() if not ok]
        if len(set(v["headers"]))!=1:
            failed.append("literal native -Zls=root")
        if not full["exact_complete_bytes"] and not full["physical_moved"]:
            failed.append("raw bytes differ with zero permuted DefIndex and no exact reconstruction")
        assert failed == v["failed"]
        if failed:
            failures[pair]=failed
        if v["unit"]=="uv_resolver":
            assert resolver is None
            resolver=v
    assert resolver and (not failures)==admit["admitted"]==(k=="S")
    assert set(failures)=={a[1] for a in admit["refused"]} and list(failures.values())==([["ctfe"]] if k=="R" else [])
    parser = tools["Z"]["C"]["Q"]["P"]
    roots,allocations,order = {},{},{}
    for s in stages:
        row=J(s+"/selected-products.json")["uv_resolver"]
        data=media[row["native_rmeta"][1]]
        assert len(data)==row["native_rmeta"][0] and scope["stages"][s]["rmeta"]==row["native_rmeta"]
        assert scope["stages"][s]["graph"]==row["native_graph"]
        reg=J("sdk/registered.json")
        banner=reg["banners"]["rustc"].splitlines()[0].removeprefix("rustc ").encode()
        header=b"RSIC"+struct.pack("<HB",reg["source"]["epoch"],len(banner))+banner
        assert raw[k+"/"+s+"/native-incremental-header.bin"]==header
        current=sha(raw[k+"/"+s+"/native-rmeta-root.txt"])
        assert current==scope["stages"][s]["native_header_sha256"]
        if s!="cold-A":
            assert current==resolver["headers"][s=="fresh-B"]
        h,defs,expansions,records,hints=parser(data,"uv_resolver")
        assert sum(records.values())==h["allocation_records"] and h["crate_name"]=="uv_resolver"
        roots[s]={n:h[n] for n in ("public_svh","private_svh","global_public_hash","stable_crate_id")}
        order[s]=h["allocation_order_sha256"]
        allocations[s]=(records,hints)
        if s!="cold-A":
            assert len(defs)==16193 and len(expansions)==1660
    assert roots["first-B"]==roots["fresh-B"] and roots["cold-A"]["public_svh"]!=roots["fresh-B"]["public_svh"]
    assert roots["cold-A"]["global_public_hash"]==roots["fresh-B"]["global_public_hash"]
    (a,ah),(b,bh)=allocations["first-B"],allocations["fresh-B"]
    assert [sum(a.values()),sum(b.values())]==([585,576] if k=="R" else [576,576])
    assert len(a)==len(b)==470 and (a==b)==(k=="S") and (order["first-B"]==order["fresh-B"])==(k=="S")
    strings={}
    variations={}
    for key in sorted(a.keys()|b.keys()):
        spell=(ah.get(key) or bh[key])["immutable_pointer_free_utf8"]
        if a[key]!=b[key]:
            variations[key]=[a[key],b[key]]
        if spell in LITERALS:
            assert spell not in strings
            strings[spell]=[a[key],b[key]]
    assert set(strings)==LITERALS and len(variations)==(19 if k=="R" else 0)
    for spell,counts in strings.items():
        expect=2 if spell=="version" else 1
        assert counts==[expect+(k=="R"),expect]
    delta_counts=[sum(max(0,v[i]-v[1-i]) for v in variations.values()) for i in (0,1)]
    assert delta_counts==([107,98] if k=="R" else [0,0])
    linked=o["linked"] if k=="R" else o["comparative_links"]
    for path,ref in linked["actual_inputs"].items():
        data=raw["linked/"+path]
        assert [len(data),sha(data)]==ref
    for s in ("A","B"):
        build,visit=J("native-build-"+s+"/command.json"),J("lock-"+s+"/command.json")
        link=linked[s]
        assert build["rc"]==visit["rc"]==0 and build["argv"]==link["cargo"] and visit["argv"]==link["command"]
        assert sha(raw[k+"/native-build-"+s+"/stderr"])==link["cargo_log"][1]
        assert sha(raw[k+"/lock-"+s+"/stderr"])==link["native_log"][1]
        lockfile=raw[k+"/lock-"+s+"/uv.lock"]
        assert sha(lockfile)==LOCK==link["TOML"]
        packages={v["name"]:v for v in tomllib.loads(lockfile.decode())["package"]}
        project=packages["uv-g-lock-root"]
        assert project["source"]=={"virtual":"."} and packages["uv-g-lock-child"]["source"]=={"editable":"child"}
        assert project["metadata"]==link["three_live_metadata_collections"] and set(project["metadata"])=={"provides-extras","requires-dev","requires-dist"}
    return {"role":k,"pid":pid,"kernel":trace_counts,"externs":62,"sidecars":471,"rmeta_paths":571,"workspace":50,
            "warm_cold_allocations":[sum(a.values()),sum(b.values())],"distinct":[len(a),len(b)],
            "allocation_order_equal":order["first-B"]==order["fresh-B"],"nine_literal_counts":strings,"whole_native_gate":admit["admitted"],
            "rmeta_pair":resolver["delta"]["warm"][1]+":"+resolver["delta"]["cold"][1],"different_paths":len(differences),"unique_pairs":len(pairs),
            "resolver_DefIndex_permutations":resolver["delta"]["physical_moved"],"resolver_dependencies":resolver["delta"]["dependencies"],
            "roots":roots,"linked_lockfile":LOCK}


def main():
    if not __debug__:
        raise RuntimeError("The source-bound metadata readers require Python assertions.")
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signed-sdk",type=Path,help="Verify every selected file in the optional original signed GNU tar.gz.")
    parser.add_argument("--corrected-sdk",type=Path,help="Verify every selected file in the optional original S Actions SDK ZIP.")
    parser.add_argument("--pair",nargs=2,type=Path,metavar=("WARM_RMETA","COLD_RMETA"),help="Decode two additional resolver files from a fresh native reproduction.")
    args=parser.parse_args()
    members=set()
    for line in (HERE/"SHA256SUMS").read_text().splitlines():
        h,n=line.split("  ",1)
        assert n not in members and PurePosixPath(n).name==n and sha_file(HERE/n)==h,n
        members.add(n)
    assert members=={"README.md","exec_events.py","metadata-kit.tar.xz","originals.tar.xz","rmeta.tar.xz","verify.py"}
    rec=pack(HERE/"originals.tar.xz",64<<20)
    j=lambda n:json.loads(rec[n])
    media=pack(HERE/"rmeta.tar.xz",96<<20)
    assert len(media)==40 and {sha(v):len(v) for v in media.values()}==j("authority/media.json")=={k:len(v)for k,v in media.items()}
    assert sum(map(len,media.values()))==61496493
    verify_git(rec,j)
    lock=verify_sdks(rec,j)
    for k,path in (("R",args.signed_sdk),("S",args.corrected_sdk)):
        if path:
            large_archive(k,path,lock)
    decode=runpy.run_path(str(HERE/"exec_events.py"))["decode"]
    with tempfile.TemporaryDirectory()as tmp:
        kit=toolkit(rec,media,Path(tmp))
        results=[verify_role(k,rec,j,media,kit,decode) for k in ("R","S")]
        report={"result":"R refused; S accepted","profile_or_clock_samples":0,"originals":results}
        if args.pair:
            data=[p.read_bytes() for p in args.pair]
            assert all(kit["Z"]["ROOT"](z)["crate_name"]=="uv_resolver" for z in data)
            fresh=kit["Z"]["delta"](*data,"uv_resolver")["semantic"]
            report["additional_input_pair"]={n:fresh[n] for n in ("raw_sha256","header","defs","changed_RDR_key_count","allocations")}
    print(json.dumps(report,sort_keys=True,indent=2))


if __name__=="__main__":
    main()
