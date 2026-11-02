#include "pub_tool_basics.h"
#include "pub_tool_tooliface.h"
#include "pub_tool_libcbase.h"
#include "pub_tool_libcprint.h"
#include "pub_tool_debuginfo.h"
#include "pub_tool_threadstate.h"
#include "pub_tool_aspacemgr.h"
#include "pub_tool_vki.h"
#include "pub_tool_libcfile.h"
#include "pub_tool_xarray.h"
#include "pub_tool_clientstate.h"
#include "libvex_guest_amd64.h"

typedef VexGuestAMD64State R;
typedef struct { UInt active; ULong serial; ULong stack; Addr dep, root_sp; UInt root_valid, root, events; } Context;
static Context ctx[1024];
static ULong seen;
static Addr bias,text_lo,text_hi;
static Bool valid(Addr p,SizeT n) { return p && VG_(am_is_valid_for_client)(p,n,VKI_PROT_READ); }
static UInt u32(Addr p) { UInt x=0; if(valid(p,4))VG_(memcpy)(&x,(void*)p,4);return x; }
static ULong u64(Addr p) { ULong x=0;if(valid(p,8))VG_(memcpy)(&x,(void*)p,8);return x; }
static UInt low(ULong x){return (UInt)x;}
static void rejected(Context *c, R *g, Addr pc, const HChar *why, Bool has_child) {
    if(!c->root_valid)return;
    Addr sp=g->guest_RSP, fr=sp+0x128;
    UInt nodes[128], depth=0;
    while(fr && depth<128 && valid(fr,12)){
        nodes[depth++]=u32(fr+8);
        Addr parent=u64(fr);
        if(parent && (parent<=fr || parent-fr>32*1024*1024))return;
        fr=parent;
    }
    if(fr||!depth||nodes[depth-1]!=c->root)return;
    c->events++;
    if(depth>1 && c->events>32)return;
    Addr graph=u64(u64(sp+0x28)+0x410),arr=u64(graph+0x18),count=u64(graph+0x20);
    UInt child=low(g->guest_R13);
    VG_(printf)("CGUR R %llu %lx %s %u",c->serial,pc,why,depth);
    for(UInt i=depth;i;i--){
        UInt x=nodes[i-1];Addr n=arr+(ULong)x*18;
        if(x>=count || !valid(n,18)){VG_(printf)(" invalid");continue;}
        VG_(printf)(" %u:%u:%016llx%016llx", x,u32(n)&65535,u64(n+2),u64(n+10));
    }
    if(has_child){
        Addr n=arr+(ULong)child*18;
        if(child<count && valid(n,18))VG_(printf)(" >%u:%u:%016llx%016llx",child,u32(n)&65535,u64(n+2),u64(n+10));
        else VG_(printf)(" >invalid");
    }
    VG_(printf)("\n");
}
static void event(ULong pc,R *g) {
    ThreadId t=VG_(get_running_tid)();
    if(t>=1024)return;
    Context *c=&ctx[t];
    if(pc==0x6ef0c18){
        if(c->active) { VG_(printf)("CGUR NESTED %llu\n",c->serial); }
        VG_(memset)(c,0,sizeof(*c));c->active=1;c->serial=++seen;c->stack=g->guest_RSP;
        VG_(printf)("CGUR E %llu %u %u\n",c->serial,t,u32(g->guest_RSI+0x40));return;
    }
    if(!c->active)return;
    switch(pc) {
      case 0x6ef0c8f: {
        HChar n[250];ULong z=g->guest_RSI;
        if(z>=sizeof(n)||!valid(g->guest_RDI,z))return;
        VG_(memcpy)(n,(void*)g->guest_RDI,z);n[z]=0;
        VG_(printf)("CGUR N %llu %s\n",c->serial,n);break; }
      case 0x6ef0c95:
        VG_(printf)("CGUR W %llu %016llx %016llx\n",c->serial,g->guest_RAX,g->guest_RDX);break;
      case 0x6ef0cc0:
        VG_(printf)("CGUR D %llu %u\n",c->serial,(UInt)(g->guest_RAX!=~(ULong)0));break;
      case 0x6ef0d6d: {
        Addr n=g->guest_RSP+0x1e;c->dep=n;
        VG_(printf)("CGUR G %llu %u %016llx %016llx\n",c->serial,u32(n)&65535,u64(n+2),u64(n+10));break;}
      case 0x5c75080:
        if(g->guest_RDX==c->dep && c->dep){c->root_sp=g->guest_RSP;VG_(printf)("CGUR T %llu\n",c->serial);}break;
      case 0x5c751b4:
        if(c->root_sp && c->root_sp==g->guest_RSP+0x88){c->root=low(g->guest_RAX);c->root_valid=1;VG_(printf)("CGUR C %llu %u %u\n",c->serial,c->root,low(g->guest_RBX));}break;
      case 0x5c662df:case 0x5c663a7:case 0x5c6644f:case 0x5c6656a:case 0x5c66603:case 0x5c6664c:case 0x5c667b3:case 0x5c66ac4:case 0x5c66150: {
        if(!c->root_valid)break;
        ULong f=LibVEX_GuestAMD64_get_rflags(g);
        Bool z=(f&64)!=0, taken=(pc==0x5c66603)||((pc==0x5c6644f||pc==0x5c66ac4)?!z:z);
        if(!taken)break;
        const HChar *why="unforceable";
        if(pc==0x5c662df)why="already-red";
        else if(pc==0x5c667b3)why="forced-red";
        else if(pc==0x5c66ac4)why="force-error";
        else if(pc==0x5c66150)why="promotion-refused";
        rejected(c,g,pc,why,pc!=0x5c66150);break;}
      case 0x6ef0eb5:
        VG_(printf)("CGUR V %llu %u %u\n",c->serial,low(g->guest_RAX),low(g->guest_RDX));break;
      case 0x7c97033: {
        ULong flags=LibVEX_GuestAMD64_get_rflags(g);
        if(!(flags&1)) { VG_(printf)("CGUR F %llu native\n",c->serial); }
        break;}
      case 0x6ef0c46:
        VG_(printf)("CGUR X %llu %u\n",c->serial,(UInt)(g->guest_RAX&255));c->active=0;break;
      default:break;
    }
}
static Bool point(Addr o){
    switch(o){
        case 0x5c75080:case 0x5c751b4:case 0x5c662df:case 0x5c663a7:case 0x5c6644f:case 0x5c6656a:case 0x5c66603:case 0x5c6664c:case 0x5c667b3:case 0x5c66ac4:case 0x5c66150:case 0x6ef0c18:case 0x6ef0c8f:case 0x6ef0c95:case 0x6ef0cc0:case 0x6ef0d6d:case 0x6ef0eb5:case 0x7c97033:case 0x6ef0c46:return True;
        default:return False;
    }
}
static IRSB *ins(VgCallbackClosure *closure,IRSB *in,const VexGuestLayout *lay,const VexGuestExtents *ext,const VexArchInfo *arch,IRType w,IRType h){
    Addr first=ext->base[0];
    if(!bias){
        DebugInfo *di=VG_(find_DebugInfo)(VG_(current_DiEpoch)(),first);
        if(di&&VG_(strstr)(VG_(DebugInfo_get_filename)(di),"librustc_driver-b03bf00bec23bb9a.so")){
            bias=VG_(DebugInfo_get_text_bias)(di);text_lo=VG_(DebugInfo_get_text_avma)(di);text_hi=text_lo+VG_(DebugInfo_get_text_size)(di);
            VG_(printf)("CGUR DRIVER %lx\n",bias);
        }
    }
    if (!bias)
        return in;
    /* BOLT puts supported paths such as the native-input veto in a separate
     * loadable .text.cold section. DebugInfo_get_text_size covers only .text.
     * Both extra ranges are taken from this exact signed ELF's section table. */
    Bool main_text = first >= text_lo && first < text_hi;
    Bool warm_text = first >= bias + 0x722a540 && first < bias + 0x722a540 + 0x11b71e;
    Bool cold_text = first >= bias + 0x7345c80 && first < bias + 0x7345c80 + 0xa4df02;
    if (!main_text && !warm_text && !cold_text)
        return in;
    Bool any=False;
    for(Int i=0;i<in->stmts_used;i++){IRStmt *s=in->stmts[i];if(s->tag==Ist_IMark&&point(s->Ist.IMark.addr-bias)){any=True;break;}}
    if(!any)return in;
    IRSB *out=deepCopyIRSBExceptStmts(in);
    for(Int i=0;i<in->stmts_used;i++){
        IRStmt *s=in->stmts[i];
        addStmtToIRSB(out,s);
        if(s->tag!=Ist_IMark)continue;
        Addr o=s->Ist.IMark.addr-bias;
        if(!point(o))continue;
        IRDirty *d=unsafeIRDirty_0_N(0,"red_cgu_read",&event,mkIRExprVec_2(mkIRExpr_HWord(o),IRExpr_GSPTR()));
        d->nFxState=1;d->fxState[0].fx=Ifx_Read;d->fxState[0].offset=0;d->fxState[0].size=sizeof(R);d->fxState[0].nRepeats=0;d->fxState[0].repeatLen=0;
        addStmtToIRSB(out,IRStmt_Dirty(d));
    }
    return out;
}
static Int fd_access(UInt n) {
    HChar path[96],buf[384];
    VG_(snprintf)(path,sizeof(path),"/proc/self/fdinfo/%u",n);
    SysRes opened=VG_(open)(path,VKI_O_RDONLY,0);
    if (sr_isError(opened))return -1;
    Int fd=(Int)sr_Res(opened),size=VG_(read)(fd,buf,sizeof(buf)-1);VG_(close)(fd);
    if(size<=0)return -1;
    buf[size]=0;HChar *p=VG_(strstr)(buf,"\nflags:\t");if(!p)return -1;
    p+=sizeof("\nflags:\t")-1;UInt mode=0,numbers=0;
    while(*p>='0'&&*p<='7'){mode=8*mode+(*p++-'0');numbers++;}
    return numbers&&*p=='\n'?(Int)(mode&3):-1;
}
static void post(void){
    ULong count=VG_(sizeXA)(VG_(args_for_client));
    VG_(printf)("CGUR CLIENT %llu %s\n",count,VG_(args_the_exename));
    for(UInt i=0;i<256;++i){struct vg_stat b;if(!VG_(fstat)(i,&b))
        VG_(printf)("CGUR FD %u %llu %llu %u %d\n",i,b.dev,b.ino,b.mode&0170000,fd_access(i));}
}
static void fini(Int rc){VG_(printf)("CGUR END %llu %d\n",seen,rc);}
static void pre(void){
    VG_(details_name)("cgu-first-red");VG_(details_version)("1");VG_(details_description)("Read signed compiler reuse decisions");
    VG_(details_copyright_author)("Local diagnostic");VG_(details_bug_reports_to)("local");VG_(basic_tool_funcs)(post,ins,fini);
}
VG_DETERMINE_INTERFACE_VERSION(pre)
