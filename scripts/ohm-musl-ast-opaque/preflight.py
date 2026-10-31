"""Apply the exact prospective reader to both full original screen archives, without materializing duplicate rlibs."""
from pathlib import Path
import gzip, json, sys, tempfile, zipfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));import run, verified_state as v
from clocked import require,sha


def rejects(f):
    try:f()
    except (ValueError,RuntimeError,AssertionError,KeyError,UnicodeDecodeError,IndexError):return True
    raise ValueError("a negative was wrongly admitted")


def check(where):
    output={}
    with tempfile.TemporaryDirectory() as temp:
        tmp=Path(temp);run.STORE=tmp;run.OUT=tmp
        for role,(i,_,_) in run.ORIGINAL.items():
            (tmp/(role+".zip")).symlink_to((where/f"{i:02}.zip").resolve())
            entries,k=run.archived(role,materialize=False)
            receipt=json.loads((tmp/(role+"-original-full-archive.json")).read_bytes())
            prefix=f"musl-measurements/{role}/proof/"
            with zipfile.ZipFile(tmp/(role+".zip")) as z:
                def get(name):
                    m=json.loads(z.read(prefix+name+"/ar-replay.json"))
                    return v.witness(m,lambda h:gzip.decompress(z.read(prefix+"ar-content/"+h+".gz")))
                a,b=get("measured-final"),get("empty")
                old=entries["measured-final"][1];new=entries["empty"][1];alt=dict(new);alt["elf"]="0"*64
                def cmp(what):return v.compare("measured-final","empty",old,what,a,b)
                negatives={"changed_native_program":rejects(lambda:cmp(alt)),"mismatched_source_state":rejects(lambda:v.compare("old","empty",old,new,a,b))}
                wrongmeta=bytearray(b[1]);wrongmeta[500000]^=1
                negatives["unrelated_rmeta_byte"]=rejects(lambda:v.opaque_metadata.prove_permutation(a[1],bytes(wrongmeta)))
                parts={n:buf for n,h,buf in v.member_readback.archive(b[0])}
                negatives["separate_file_disagrees_with_real_elf"]=rejects(lambda:v.rmeta_offset(parts["lib.rmeta"],a[1]))
                alt=dict(new);alt["symbols"]="0"*64;negatives["symbol_table"]=rejects(lambda:cmp(alt))
                alt=dict(new);alt["objects"]="f"*64;negatives["native_object_inventory"]=rejects(lambda:cmp(alt))
            output[role]={"source_rmeta_bytes":receipt["forward"]["rmeta_bytes"],"source_ar":receipt["forward"]["source_ar"],"reconstructed_ar":receipt["forward"]["reencoded_ar"],"return_ar":receipt["reverse"]["reencoded_ar"],"field_counts":receipt["forward"]["separate_rmeta"]["by_field"],"mutations":negatives}
    return output
if __name__=="__main__":print(json.dumps(check(Path(sys.argv[1])),sort_keys=True,indent=2))
