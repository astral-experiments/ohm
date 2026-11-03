"""Re-encode a permutation of lazy synthetic defs from one rustc metadata image.

The other image supplies only the proposed DefPathHash ordering. No payload
bytes from it enter construction. The caller separately checks the native
headers, per-DefPathHash fingerprints, dependencies, expansions and CTFE.
"""
import struct
from hashlib import sha256
from collections import Counter


def check(ok, message):
    if not ok:
        raise ValueError(message)


def var(n):
    check(0 <= n < 1 << 64, 'integer outside u64')
    out = bytearray()
    while n >= 128:
        out.append(128 | (n & 127))
        n >>= 7
    return bytes(out) + bytes([n])


def read(data, p):
    at, n = p, 0
    for shift in range(0, 70, 7):
        byte = data[p]
        p += 1
        n |= (byte & 127) << shift
        if byte < 128:
            check(data[at:p] == var(n), 'noncanonical integer')
            return n, p
    raise ValueError('unterminated integer')


def full_span(data, p):
    at = p
    tag = data[p]
    p += 1
    kind = tag & 3
    check(kind < 3, 'shorthand as full span')
    if not (tag & 4):
        _, p = read(data, p)
    if kind != 2:
        _, p = read(data, p)  # file-relative lo
        if tag >> 3 == 31:
            _, p = read(data, p)
        _, p = read(data, p)  # source file index
        if kind == 1:
            _, p = read(data, p)  # foreign crate
    return data[at:p], p


def original_span(data, p):
    tag = data[p]
    if tag & 3 != 3:
        _, end = full_span(data, p)
        return p, end
    width = tag >> 3
    check(1 <= width <= 8, 'span distance width')
    n = int.from_bytes(data[p+1:p+1+width], 'little')
    target = p - n if tag & 4 else n
    check(0 < target < p and data[target] & 3 != 3, 'span referent')
    check(span_ref(p, target) == data[p:p+1+width], 'noncanonical span offset')
    return target, p+1+width


def span_ref(p, target):
    check(0 < target < p, 'forward span')
    offset = p-target
    relative = offset < target
    value = offset if relative else target
    width = max(1, (value.bit_length()+7)//8)
    return bytes([(width << 3) | (4 if relative else 0) | 3]) + value.to_bytes(width, 'little')


def local_key(data, p):
    # The stable-hash rmeta encoder writes a supplying CrateNum then Hash64.
    crate, p = read(data, p)
    check(p+8 <= len(data), 'short Hash64')
    return (crate, data[p:p+8]), p+8


def simple_generics(data, start, parent, local_keys, item_start):
    """Resolve each generic parameter and reverse-map key in declaration order."""
    check(data[start] == 1, 'generics parent is absent')
    owner, p = local_key(data, start+1)
    check(owner == (0, parent), 'generics parent identity')
    parent_count, p = read(data, p)
    count, p = read(data, p)
    check(parent_count < 65536 and count < 4096, 'unsupported generic arity')
    params = []
    for _ in range(count):
        # No new strings from a reordered record. Offset symbols must already
        # exist outside the earliest movable stream.
        tag = data[p]
        check(tag in (1,2), 'parameter introduces new string')
        sym, p = read(data,p+1)
        if tag == 1:
            check(0 < sym < item_start, 'parameter-name offset crosses moved item data')
            length,body=read(data,sym)
            data[body:body+length].decode()
            check(data[body+length]==193,'invalid parameter-name symbol')
        param, p = local_key(data, p)
        check(param[0] or param[1] in local_keys, 'missing local generic parameter')
        index,p = read(data,p)
        check(data[p] in (0,1) and data[p+1] <= 2,'generic drop flag or kind')
        kind = data[p+1]
        p += 2
        nflags = (0,2,1)[kind]
        check(all(x in (0,1) for x in data[p:p+nflags]),'generic kind flags')
        p += nflags
        params.append((param,index))
    n,p = read(data,p)
    check(n==count, 'generic reverse index length')
    for expected in params:
        param,p = local_key(data,p)
        index,p = read(data,p)
        check((param,index)==expected, 'generic reverse key/order')
    check(data[p] in (0,1) and data[p+1]==0, 'late-bound parameter span present')
    return p+2


def encode_table(cells):
    """Exact TableBuilder::set/encode/decode column representation."""
    while cells and not any(cells[-1]):
        cells.pop()
    n = len(cells)
    width = max((len(c.rstrip(b'\0')) for c in cells), default=0)
    present = sum(any(c) for c in cells)
    dense = width*n
    price = 12*((n+63)//64)
    # Native encoder keeps sparse strictly smaller, including its 1-byte flag cost.
    sparse = bool(present and price + 1 < dense and present <= (dense-price-2)//width)
    normalized = [c[:width].ljust(width,b'\0') for c in cells]
    if not sparse:
        return width, n, False, b''.join(normalized)
    bitmaps = bytearray()
    value_bytes = bytearray()
    prefix = 0
    for start in range(0,n,64):
        group = normalized[start:start+64]
        bits = sum(1 << i for i,c in enumerate(group) if any(c))
        bitmaps.extend(struct.pack('<QI',bits,prefix))
        prefix += bits.bit_count()
        value_bytes.extend(b''.join(c for c in group if any(c)))
    return width,n,True,bytes(bitmaps + value_bytes)


def array_value(cell):
    cell = cell.ljust(16,b'\0')
    return int.from_bytes(cell[::2],'little'), int.from_bytes(cell[1::2],'little')


def array_cell(p,n):
    out = bytearray(16)
    out[::2] = p.to_bytes(8,'little')
    out[1::2] = n.to_bytes(8,'little')
    return bytes(out)


# Derived from the checked rustc_metadata::rmeta table declarations.
ARRAYS = frozenset('ambig_module_children associated_item_or_field_def_ids assumed_wf_types_for_rpitit attributes deduced_param_attrs doc_link_traits_in_scope explicit_implied_clauses_of explicit_implied_const_bounds explicit_item_bounds explicit_item_self_bounds explicit_super_clauses_of fn_arg_idents inferred_outlives_of inherent_impls module_children_non_reexports module_children_reexports rendered_precise_capturing_args variances_of'.split())
POINTERS = frozenset('adt_async_destructor adt_destructor anon_const_kind args_known_to_outlive_alias_params assoc_container associated_types_for_impl_traits_in_trait_or_impl closure_saved_names_of_captured_variables codegen_fn_attrs coerce_unsized_info collect_return_position_impl_trait_in_trait_tys const_conditions const_of_item const_param_default def_ident_span def_keys def_span default_fields doc_link_resolutions eval_static_initializer explicit_clauses_of expn_data expn_hashes expn_that_defined fn_sig generics_of impl_trait_header intrinsic live_args_for_alias_from_outlives_bounds lookup_const_stability lookup_default_body_stability lookup_deprecation_entry lookup_stability macro_definition mir_const_qualif mir_coroutine_runtime_info mir_coroutine_witnesses mir_for_ctfe mut_restriction object_lifetime_default opaque_ty_origin opt_rpitit_info optimized_mir params_in_repr promoted_mir rendered_const repr_options source_map syntax_contexts thir_abstract_const trait_def trivial_const type_of variant_data visibility'.split())


class Patches:
    def __init__(self, data):
        self.data = data
        self.patches = {}
        self.tallies = Counter()

    def write(self, low, high, result, why):
        check(0 <= low <= high <= len(self.data), 'outside source')
        if self.data[low:high] == result:
            return
        previous = self.patches.get((low,high))
        check(previous is None or previous[0] == result, 'inconsistent overlapping source fields')
        if previous is None:
            self.patches[low,high] = result, why
            self.tallies[why] += 1

    def image(self):
        start, out = 0, bytearray()
        for (low,high),(result,why) in sorted(self.patches.items()):
            check(start <= low, 'overlapping typed source fields: '+why)
            out.extend(self.data[start:low])
            out.extend(result)
            start = high
        out.extend(self.data[start:])
        return bytes(out)


def cellptr(cells, name, index):
    col = cells[name]
    return int.from_bytes(col[index],'little') if index < len(col) else 0


def reencoded(left, right, root_reader, di, defkeys):
    a = root_reader(left)
    b = root_reader(right)
    for k in ('target','crate_name','stable_crate_id','private_svh','public_svh','global_public_hash'):
        check(a[k]==b[k],'different native '+k)
    tables, target_tables = a['tables'], b['tables']
    check(list(tables) == list(target_tables), 'root field schema')
    signed = di.keyed(left,a)
    observed = di.keyed(right,b)
    check(len(signed)==len(set(signed))==len(observed) and set(signed)==set(observed), 'stable definition roster')
    to = {k:i for i,k in enumerate(observed)}
    perm = [to[k] for k in signed]
    inverse = [0]*len(perm)
    for i,j in enumerate(perm):
        inverse[j] = i
    mv = [i for i,j in enumerate(perm) if i!=j]
    check(bool(mv), 'no synthetic permutation')
    by_key = set(signed)
    cols = {k:list(di.rows(left,t)) for k,t in tables.items() if t['type']=='table'}
    op = Patches(left)
    keys = []
    kp = []
    key_ends = []
    old_num = {}
    # Native stable identities authorize the reordering and independent decoder
    # checks each resolved parent, namespace, spelling and disambiguator.
    target_key_cells = list(di.rows(right,target_tables['def_keys']))
    for i,h in enumerate(signed):
        p = cellptr(cols,'def_keys',i)
        k,end = defkeys.key_at(left,p,signed)
        d,q = defkeys.key_at(right,int.from_bytes(target_key_cells[perm[i]],'little'),observed)
        check(k==d, 'DefKey structure changed')
        kp.append(p); keys.append(k); key_ends.append(end)
        if k['parent'] is not None:
            check(left[p]==1, 'DefKey parent tag')
            parent,z = read(left,p+1)
            check(parent<len(signed),'DefKey parent out of range')
            old_num[i] = parent,z
    check(key_ends[:-1] == kp[1:], 'noncontiguous DefKey stream')
    # Restrict generated records to shapes for which all nested refs are
    # re-encoded below. Ordinary source definitions cannot enter this projection.
    start,end = min(mv),max(mv)+1
    for i in range(start,end):
        check(keys[i]['kind'] in ('AnonAssocTy','OpaqueLifetime','SyntheticCoroutineBody'), 'ordinary row inside synthetic run')
        check(old_num[i][0] < start, 'synthetic parent inside reordered run')
        _,z=read(left,old_num[i][1])  # DefPathData tag
        if keys[i]['kind']=='SyntheticCoroutineBody':
            disamb,stop=read(left,z)
            check(stop==key_ends[i] and disamb==keys[i]['disambiguator'],
                  'invalid nameless SyntheticCoroutineBody DefKey')
            continue
        form=left[z]
        check(form in (1,2),'reordered DefKey publishes a new name')
        sym,_=read(left,z+1)
        if form==1: check(0<sym<kp[start],'DefKey symbol points inside reorder')
    new_position = {}
    out = bytearray()
    for j,i in enumerate(inverse):
        p,stop = kp[i],key_ends[i]
        new_position['def_keys',i] = kp[0]+len(out)
        if i in old_num:
            old,z = old_num[i]
            out += b'\1' + var(perm[old]) + left[z:stop]
        else:
            out += left[p:stop]
    check(len(out)==key_ends[-1]-kp[0], 'variable-width DefKey stream')
    op.write(kp[0],key_ends[-1],out,'DefKey records and physical parents')

    # Three actual per-item DefIndex arrays. CrateRoot also has two direct
    # DefIndex slices. The stable-hash EncodedTraitImpls is a different type.
    def rewrite_indices(p,n):
        start_pos = p
        buf = bytearray()
        for _ in range(n):
            index,p = read(left,p)
            check(index < len(perm),'index slice out of range')
            buf.extend(var(perm[index]))
        check(len(buf)==p-start_pos,'DefIndex array changes byte length')
        op.write(start_pos,p,buf,'typed arrays of physical DefIndex')
    for name in ('associated_item_or_field_def_ids','inherent_impls','module_children_non_reexports'):
        for c in cols[name]:
            p,n = array_value(c)
            if n: rewrite_indices(p,n)
    for name in ('traits','exportable_items'):
        t=tables[name]
        if t['length']: rewrite_indices(t['position'],t['length'])

    # Per-item metadata: spans, an empty attributes anchor, and for RPITIT
    # visibility, simple Generics, empty inherited clauses and an absolute Ty
    # shorthand. The latter three publish no new symbol/type cache positions.
    rows={}
    data_start = cellptr(cols,'def_span',start)
    from coroutine_rows import CoroutineTypes, EMPTY_CODEGEN
    coroutine_types=CoroutineTypes(left,data_start,{k:v['kind'] for k,v in zip(signed,keys,strict=True)})
    p=data_start
    for i in range(start,end):
        parts=[]
        check(p==cellptr(cols,'def_span',i),'noncontiguous item start')
        synthetic=keys[i]['kind']=='SyntheticCoroutineBody'
        if synthetic:
            check(i>=len(cols['def_ident_span']) or not any(cols['def_ident_span'][i]), 'coroutine with ident span')
        for tag in (('def_span',) if synthetic else ('def_span','def_ident_span')):
            check(cellptr(cols,tag,i)==p,'item span position')
            if tag=='def_ident_span' and keys[i]['kind']=='AnonAssocTy':
                check(array_value(cols['attributes'][i])==(p,0),'nonempty RPITIT attrs')
            ptr,stop=original_span(left,p)
            parts.append((tag,p,stop,ptr));p=stop
        if keys[i]['kind']=='AnonAssocTy':
            check(cellptr(cols,'visibility',i)==p and left[p] in (0,1),'unsupported synthetic visibility')
            q=p+1
            if left[p]==1:
                who,q=read(left,q)
                check(who<len(perm) and perm[who]==who and keys[who]['kind'] in ('CrateRoot','TypeNs'),'restricted visibility module')
            parts.append(('visibility',p,q,None));p=q
        if synthetic:
            check(cellptr(cols,'codegen_fn_attrs',i)==p and left[p:p+len(EMPTY_CODEGEN)]==EMPTY_CODEGEN,
                  'nonempty coroutine codegen attributes')
            q=p+len(EMPTY_CODEGEN)
            parts.append(('codegen_fn_attrs',p,q,None));p=q
        if synthetic or keys[i]['kind']=='AnonAssocTy':
            check(cellptr(cols,'generics_of',i)==p,'noncontiguous synthetic Generics')
            parent=signed[old_num[i][0]]
            if synthetic:
                check(left[p]==1,'missing coroutine generic parent')
                (crate,parent),_=local_key(left,p+1)
                ancestor=old_num[i][0]
                while signed[ancestor]!=parent and ancestor in old_num:
                    previous=old_num[ancestor][0]
                    check(previous<ancestor,'cyclic coroutine ancestry')
                    ancestor=previous
                check(crate==0 and signed[ancestor]==parent,'coroutine generics outside lexical ancestors')
            q=simple_generics(left,p,parent,by_key,data_start)
            parts.append(('generics_of',p,q,None));p=q
            check(cellptr(cols,'explicit_clauses_of',i)==p and left[p]==1,'missing explicit clauses')
            who,q=local_key(left,p+1)
            check(who==(0,parent) and left[q]==0,'nonempty or incorrect inherited clauses')
            parts.append(('explicit_clauses_of',p,q+1,None));p=q+1
            check(cellptr(cols,'type_of',i)==p,'incorrect synthetic type position')
            if not synthetic:check(left[p]&128,'uncached associated type')
            ptr,q=coroutine_types.original(p)
            parts.append(('type_of',p,q,ptr));p=q
        rows[i]=parts
    old_end=p
    out=bytearray()
    full_positions={}
    for j in range(start,end):
        i=inverse[j]
        for tag,p,q,ptr in rows[i]:
            now=data_start+len(out)
            new_position[tag,i]=now
            if tag=='def_ident_span' and keys[i]['kind']=='AnonAssocTy':
                new_position['attributes',i]=now
            if tag=='type_of':
                out+=coroutine_types.encoded(ptr,now)
            elif ptr is None:
                out += left[p:q]
            elif ptr<data_start:
                out += span_ref(now,ptr)
            elif ptr in full_positions:
                out += span_ref(now,full_positions[ptr])
            else:
                check(data_start<=ptr<old_end,'unowned full span')
                full_positions[ptr]=now
                full,_=full_span(left,ptr)
                out += full
    coroutine_types.external(left,cols['type_of'],old_end,op)
    delta=len(out)-(old_end-data_start)
    op.write(data_start,old_end,out,'typed item records and backreferences')

    shifted=[(old_end,delta)] if delta else []
    def relocate(ptr):
        check(not (data_start<=ptr<old_end),'unclassified incoming pointer into reordered span stream')
        return ptr+sum(change for endpos,change in shifted if endpos<=ptr)
    # No full Span may escape an unaccounted-for field with a stale old
    # address. All direct span table *values* get checked/re-encoded and the
    # two native full/indirect encodings of each referenced span are validated.
    recognized_span=set()
    for tag in ('def_span','def_ident_span'):
        for i,c in enumerate(cols[tag]):
            if not any(c):continue
            p=int.from_bytes(c,'little')
            recognized_span.add(p)
            if start<=i<end:continue
            ptr,q=original_span(left,p)
            if ptr==p:continue
            dest=full_positions[ptr] if ptr in full_positions else relocate(ptr)
            encoded=span_ref(relocate(p),dest)
            check(len(encoded)==q-p,'changed external span shorthand width')
            op.write(p,q,encoded,'other span backreferences')
    # The same real default-growth and SwissTable insert sequence regenerates
    # every sentinel, occupied bucket, probe placement and strong index.
    from odht_wire import def_path_hash_map as encode_odht
    ln,p=read(left,tables['def_path_hash_map']['position'])
    check(left[p:p+ln]==encode_odht(signed),'native ODHT source/growth control')
    projected_map=encode_odht(observed)
    check(len(projected_map)==ln,'ODHT allocation shape changed')
    op.write(p,p+ln,projected_map,'complete native Hash64 ODHT')

    source_table_names=list(tables)
    first=next(i for i,k in enumerate(source_table_names)if tables[k]['type']=='table')
    last=source_table_names.index('syntax_contexts')
    local=set(source_table_names[first:last])|{'rdr_hashes.local'}
    emitted={}
    for name in sorted(cols,key=lambda k:(tables[k]['position'],tables[k]['end'])):
        t,vals=tables[name],cols[name]
        sw,sl,ss,column=encode_table(list(vals))
        check((sw,sl,ss)==(t['width'],t['length'],t['sparse']) and column==left[t['position']:t['end']], 'native input table encoder: '+name)
        if name in local:
            vals=vals+[b'']*(len(perm)-len(vals))
            check(len(vals)==len(perm),'wrong native table index domain')
            order=inverse
        else:order=range(len(vals))
        target=[]
        for i in order:
            value=vals[i]
            owned=(name,i)in new_position
            if any(value) and (name in ARRAYS or name in POINTERS or owned):
                isarray=name in ARRAYS
                oldp,n=array_value(value) if isarray else (int.from_bytes(value,'little'),0)
                if owned:
                    now=new_position[name,i]
                else:
                    now=relocate(oldp)
                value=array_cell(now,n)if isarray else now.to_bytes(8,'little')
            target.append(value)
        w,n,sparse,raw=encode_table(target)
        nt=target_tables[name]
        check((w,n,sparse)==(nt['width'],nt['length'],nt['sparse']), 'target table geometry: '+name)
        check(relocate(t['position'])==nt['position'], 'table ordering/position: '+name)
        emitted[name]=(w,n,sparse)
        op.write(t['position'],t['end'],raw,'root-indexed table columns')
        d=len(raw)-(t['end']-t['position'])
        if d:shifted.append((t['end'],d))

    from metadata_refs import rewrite
    rewrite(left,a,cols,op,relocate,full_positions,recognized_span,docs_only=not shifted)
    # A hidden shorthand anywhere in the complete file to a moved newly
    # published full span must not be treated as inert. False byte-pattern
    # matches are conservative refusals. The inverse pass covers both images.
    redirected={src for src,dst in full_positions.items() if src!=dst}
    if redirected:
        for p in range(data_start,len(left)):
            tag=left[p]
            if tag&3!=3 or not (1<=tag>>3<=8) or p in recognized_span:continue
            n=tag>>3
            val=int.from_bytes(left[p+1:p+1+n],'little')
            ptr=p-val if tag&4 else val
            if ptr in redirected and 0<ptr<p:
                check(left[p:p+n+1]!=span_ref(p,ptr),'unowned span shorthand into moved full span')

    new_root=relocate(a['root'])
    check(new_root==b['root'] and int.from_bytes(left[8:16],'little')==a['root'],'native root header/cursor')
    op.write(8,16,new_root.to_bytes(8,'little'),'CrateRoot absolute position')

    # Trace the admitted source-version root parser's actual lazy descriptor
    # bounds. Independently re-encode every field in each direction. Seventeen
    # array/value fields interleave constant header fields with the columns.
    base=root_reader.__globals__['R']['Reader21']
    ranges={}
    class Trace(base):
        def table(self,k):
            p=self.p;super().table(k);ranges[k]=p,self.p
        def value(self,k):
            p=self.p;super().value(k);ranges[k]=p,self.p
        def array(self,k):
            p=self.p;super().array(k);ranges[k]=p,self.p
    trace=Trace(left,a['root'])
    check(trace.read()['tables']==tables and list(ranges)==source_table_names,'native root descriptor trace')
    prev=prev_new=None
    for k,t in tables.items():
        ty=t['type'];p=t['position'];q=None if p is None else relocate(p)
        check(q==target_tables[k]['position'],'root pointer '+k)
        old,new=bytearray(),bytearray()
        if ty=='array':
            old+=var(t['length']);new+=var(t['length'])
        elif ty=='table':
            old+=var(t['width']|(128 if t['sparse']else 0))+var(t['length'])
            w,n,sp=emitted[k];new+=var(w|(128 if sp else 0))+var(n)
        else:check(ty=='value','unknown root descriptor')
        if p is not None:
            old+=var(a['root']-p if prev is None else p-prev)
            new+=var(new_root-q if prev_new is None else q-prev_new)
            prev,prev_new=p,q
        low,high=ranges[k]
        if k==source_table_names[first]:
            check(left[low] in (0,1) and high-low==len(old)+1,'unexpected CrateRoot flag before tables')
            low+=1
        check(left[low:high]==old,'native root descriptor: '+k)
        op.write(low,high,new,'CrateRoot lazy descriptors')
    result=op.image()
    return result,{'definitions':len(signed),'moved':len(mv),'moved_classes':dict(Counter(keys[i]['kind']for i in mv)),'changed_regions':dict(op.tallies),'full_bytes_reconstructed':len(result),'reconstructed_sha256':sha256(result).hexdigest()}


def project(left, right, root_reader, di, defkeys, explain=False):
    result,details=reencoded(left,right,root_reader,di,defkeys)
    if result!=right and explain:
        diffs=[i for i,(x,y)in enumerate(zip(result,right)) if x!=y]
        raise ValueError('unexplained native bytes '+str((len(diffs),diffs[:55],len(result),len(right))))
    check(result==right,'unexplained native bytes')
    return details
