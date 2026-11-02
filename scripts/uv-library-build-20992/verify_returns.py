"""Reopen the two physical compiler switches and their Cargo images, subprocesses and outputs."""
import native
import kernel
import evidence

def reopen():
    root=native.ROOT;records=native.read(root/"preclock-role-returns.json");assert set(records)=={"parent","candidate"}
    for role,receipt in records.items():
        prior=root/f"opening-{role}-1";dest=root/("preclock-return-"+role);p=dest/"process"
        sdk=native.read(prior/"sdk.json");assert sdk["launcher_file"]==receipt["launcher"] and sdk["cargo_file"]==receipt["cargo"]
        for n in ("launcher_file","cargo_file","source","driver"):
            assert all(native.read(root/f"opening-{role}-{pair}/sdk.json")[n]==sdk[n] for pair in range(2,9))
        actual=native.read(p/"observed-rustcs.json");k=kernel.EVENTS["decode"](native.read(p/"kernel-events.json"))
        assert actual["kernel_sha"]==native.sha(p/"kernel-events.json") and k["root"]==actual["root"] and k["exits"][k["root"]]==0
        cargo,=[x for x in k["images"]if x["pid"]==k["root"]];assert cargo["file"]==sdk["cargo_file"] and cargo["argv"]==actual["cargo"]==kernel.command()
        other=[];targets={}
        for image in k["images"]:
            if image["file"]!=sdk["launcher_file"]:continue
            args=image["argv"];pid=image["pid"];assert k["exits"][pid]==0 and args[0]==str(native.SDK/"bin/rustc")
            if "--crate-name" not in args:other.append(args);continue
            name=args[args.index("--crate-name")+1];assert name not in targets
            targets[name]=dict(argv=args,pid=pid,exe=image["exe"],inode=image["file"],exit=0)
        assert set(targets)=={"build_script_build","uv_python"}and targets==actual["targets"]
        assert sorted(other)==actual["other_rustc_queries"]==receipt["rustc_queries"]
        assert kernel.match(native.read(prior/"A-kernel/process/observed-rustcs.json"),actual)==receipt["kernel"]
        result=evidence.compare(native.read(prior/"anchor-A/native-products.json"),native.read(dest/"native-products.json"),"A")
        assert native.read(dest/"all-products.json")==result and receipt["all_products"]==native.sha(dest/"all-products.json")
        linked=native.read(dest/"linked.json");native.linked.check_probe(linked)
        assert linked["execute"]["stdout"]==native.read(prior/"anchor-A/linked.json")["execute"]["stdout"] and receipt["behavior"]==native.sha(dest/"linked.json")
    return native.sha(root/"preclock-role-returns.json")
