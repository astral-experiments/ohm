"""Bind an untraced Apple product to its retained root .rlink and every complete root object."""
from pathlib import Path
import gzip
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import *
from fixture import APP

def modules():
    sys.path.insert(0,str(seed('apple-reader')/'scripts/ohm-apple-zmij'))
    import cgu_inputs
    return cgu_inputs

def witness(root,out,work,body,published,script_out):
    """Xcode can clone the promoted Mach-O; bind its complete bytes in the active Cargo namespace."""
    staged=Path(script_out).resolve();owner=staged.parent.parent
    require(staged.name=='out' and owner.name==APP and owner.parent.name.startswith('v2-') and owner.is_relative_to(work/'target'),'inactive Cargo workspace')
    active=[]
    for recipe in owner.glob('*/out/'+APP+'.rlink'):
        native=recipe.with_suffix('')
        if native.is_file() and not native.is_symlink() and native.read_bytes()==body:
            active.append(native)
    require(len(active)==1,('no unique complete Mach-O in the active Cargo crate',active,str(published)))
    native,=active;pub,private=ident(published),ident(native)
    require(pub['bytes']==private['bytes']==len(body) and pub['sha256']==private['sha256']==hashlib.sha256(body).hexdigest(),'different promoted program')
    save(out/'promotion.json',{'typed_script_out':str(staged),'published':pub,'private':private,'same_inode':published.samefile(native)})
    return modules().witness(root,out,body,str(native))

def reopen(root,body,proof):
    """Reconstruct the same permitted Mach-O edits from the archived compiler-owned recipe and objects."""
    cgu=modules()
    def blob(kind,key):
        f=root/'cgu-inputs'/kind/(key+'.gz');b=gzip.decompress(f.read_bytes())
        require(hashlib.sha256(b).hexdigest()==key,(kind,key));return b
    require(proof['source']=='saved-rustc-recipe' and proof['raw']==hashlib.sha256(body).hexdigest(),'incorrect native evidence scope')
    version,rows=cgu.modules(blob('recipes',proof['recipe']))
    require(version==proof['version'],'different recipe')
    native=Path(proof['output'])
    physical={};by_name={}
    for row in rows:
        path=Path(row['object']);name=row['name']
        require(path.is_absolute() and path.parent==native.with_suffix('.rlink-objects') and path.suffix=='.o','foreign native object')
        entry=proof['physical'][str(path)];obj=blob('objects',entry['sha256'])
        require(entry=={'module':name,'kind':row['kind'],'sha256':hashlib.sha256(obj).hexdigest(),'bytes':len(obj)} and obj[:8]==bytes.fromhex('cffaedfe0c000001') and int.from_bytes(obj[12:16],'little')==1,'wrong native object')
        physical[str(path)]=entry;by_name[name]=entry['sha256']
    require(physical==proof['physical'] and by_name==proof['modules'],'incomplete root recipe')
    normalized,checks=cgu.canonical(body,str(native),[*physical,'-o',str(native)],incremental=True,namespace=False)
    require(checks['nonce_objects']==proof['nonce_objects'] and checks['code_pages']==proof['code_pages'] and all(n['path'] in physical and cgu.root_cgu(n['path'],str(native)) for n in checks['nonce_objects']),'unknown Mach-O comparison')
    require(hashlib.sha256(normalized).hexdigest()==proof['same_path_image'],'unknown other Mach-O bytes')
    return (str(native),proof['same_path_image'],tuple(sorted(by_name.items())))
