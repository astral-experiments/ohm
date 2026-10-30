"""Attribute actual bytes in a pair of complete BSD rlibs without accepting a masked archive."""
import hashlib,struct

def sha(b):return hashlib.sha256(b).hexdigest()
def named_members(data):
    assert data[:8]==b'!<arch>\n'
    i=8;rows=[]
    while i<len(data):
        head=data[i:i+60];length=int(head[48:58]);assert head[58:60]==b'`\n' and head[:3]==b'#1/'
        w=int(head[3:16]);start=i+60;end=start+length
        nm=data[start:start+w].rstrip(b'\0').decode('ascii');body=data[start+w:end]
        rows.append((nm,head,body,data[end:end+length%2]));i=end+length%2
    assert i==len(data)
    return rows

def changes(a,b):
    first=next((i for i,(x,y) in enumerate(zip(a,b)) if x!=y),min(len(a),len(b)))
    last=0
    while last<min(len(a),len(b))-first and a[len(a)-1-last]==b[len(b)-1-last]:last+=1
    ans={'size':[len(a),len(b)],'sha256':[sha(a),sha(b)],'shared_prefix':first,'shared_suffix':last}
    if len(a)==len(b):
        count=0;ranges=[];start=None
        for i,(x,y) in enumerate(zip(a,b)):
            count+=x!=y
            if x!=y and start is None:start=i
            elif x==y and start is not None:ranges.append([start,i]);start=None
        if start is not None:ranges.append([start,len(a)])
        ans.update(different_bytes=count,ranges=len(ranges),first_twelve_offsets=ranges[:12])
    return ans

def census(a,b):
    aa,bb=named_members(a),named_members(b)
    if len(aa)!=len(bb):return {'whole_sizes':[len(a),len(b)],'member_counts':[len(aa),len(bb)],'left':[x[0] for x in aa],'right':[x[0] for x in bb]}
    out={'whole':changes(a,b),'member_count':len(aa),'same_all_raw_member_names':False,'changed_names':[],'changed_headers':[],'changed_special_members':{},'changed_native_members':[]}
    for i,((x,h,body,align),(y,k,other,align2)) in enumerate(zip(aa,bb)):
        if x!=y:out['changed_names'].append([x,y])
        if h!=k or align!=align2:out['changed_headers'].append([i,x,y])
        if body==other:continue
        if x.startswith('__.SYMDEF') or x in ('lib.rmeta','lib.rmeta-link'):
            out['changed_special_members'][x]={'other':y,**changes(body,other)}
        else:out['changed_native_members'].append([i,x,y,len(body),len(other),sha(body),sha(other)])
    out['same_all_raw_member_names']=not out['changed_names']
    return out
