//! Scoped Linux/ELF experiment. Full file snapshots supply both parsing and the proof.
//! The witness lives under an explicitly private, per-run cache; no arbitrary suffix rewriting.
use crate::file_kind::FileKind;
use crate::fs::{FileSystem, InputFileData};
use crate::input_data::{FileLoader, InputRef};
use crate::linker_script::Command;
use crate::platform::{Args as _, Platform};
use crate::resolution::{ResolvedFile, ResolvedGroup};
use object::{Object, ObjectSymbol};
use std::fs::{File, Metadata, OpenOptions};
use std::io::{self, Read, Write};
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::OnceLock;

struct Config {
    root: PathBuf,
    output: PathBuf,
    symbols: PathBuf,
    raw: PathBuf,
    resolution: PathBuf,
    args_digest: [u8; 32],
}
static CONFIG: OnceLock<Option<Config>> = OnceLock::new();
static WARNING: AtomicBool = AtomicBool::new(false);
static CANDIDATE: OnceLock<Candidate> = OnceLock::new();
static PRODUCED: OnceLock<[u8; 32]> = OnceLock::new();

pub(crate) fn note_warning() { WARNING.store(true, Ordering::Relaxed); }
fn config() -> Option<&'static Config> { CONFIG.get_or_init(parse).as_ref() }
pub(crate) fn active() -> bool { config().is_some() }
fn part(h: &mut blake3::Hasher, v: &[u8]) {
    h.update(&(v.len() as u64).to_le_bytes());
    h.update(v);
}
fn number(h: &mut blake3::Hasher, v: usize) { part(h, &(v as u64).to_le_bytes()); }
fn path_bytes(p: &Path) -> &[u8] { p.as_os_str().as_encoded_bytes() }
fn fail<T>(why: &'static str) -> Option<T> { event(why); None }
pub(crate) fn event(label: &str) {
    if let Some(p) = std::env::var_os("OHM_WILD_OBSERVATION_EVENTS") {
        if let Ok(mut f) = OpenOptions::new().create(true).append(true).mode(0o600).open(p) {
            let line=format!("{} {label}\n", std::process::id());
            let _ = f.write_all(line.as_bytes());
        }
    }
}
fn parse() -> Option<Config> {
    let root = PathBuf::from(std::env::var_os("OHM_WILD_OBSERVATION_CACHE")?);
    let meta = root.symlink_metadata().ok()?;
    if !meta.is_dir() || meta.mode() & 0o077 != 0 || meta.uid() != unsafe { libc::geteuid() } || root.canonicalize().ok()? != root { return None }
    if std::env::vars_os().any(|(k,_)| k.as_encoded_bytes().starts_with(b"WILD_") || matches!(k.to_str(),Some("RUST_LOG"|"LD_PRELOAD"|"LD_AUDIT"))) { return fail("bypass-env") }
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    let mut h=blake3::Hasher::new(); part(&mut h,b"observation-replay-1");
    part(&mut h,blake3::hash(&std::fs::read("/proc/self/exe").ok()?).as_bytes());
    part(&mut h,path_bytes(&std::env::current_dir().ok()?));
    let (mut sym,mut raw,mut res,mut out,mut pie)=(None,None,None,None,false);
    let mut i=0;
    while i<args.len() {
        let a=&args[i]; i+=1;
        let mut value=a.as_bytes();
        if let Some(dir)=a.strip_prefix("-L") {
            if !Path::new(dir).is_absolute() { return fail("bypass-L") }
            if Path::new(dir).file_name().is_some_and(|n| n=="raw-dylibs") {
                if raw.replace(PathBuf::from(dir)).is_some() { return None }
                value=b"<raw-directory>";
            }
        } else if let Some(p) = a.strip_prefix("-plugin-opt=-fresolution=") {
            if !Path::new(p).is_absolute() || res.replace(PathBuf::from(p)).is_some() { return None }
            value=b"<unused-gcc-resolution>";
        } else if a.starts_with("-plugin-opt=/") || a.starts_with("-l") && a.len()>2 && a[2..].bytes().all(|c|c.is_ascii_alphanumeric()||c==b'_') {
        } else if matches!(a.as_str(), "-plugin"|"-m"|"-dynamic-linker"|"-o"|"-z") {
            let b=args.get(i)?; i+=1;
            if a=="-o" { if !Path::new(b).is_absolute() || out.replace(PathBuf::from(b)).is_some() { return None } }
            else if a=="-z" && !matches!(b.as_str(),"now"|"relro"|"noexecstack") || a=="-m" && b!="elf_x86_64" || matches!(a.as_str(),"-plugin"|"-dynamic-linker") && !Path::new(b).is_absolute() { return None }
            part(&mut h,a.as_bytes());part(&mut h,b.as_bytes());continue
        } else if a=="-pie" { pie=true; }
        else if matches!(a.as_str(),"--build-id"|"--eh-frame-hdr"|"--hash-style=gnu"|"--as-needed"|"-Bstatic"|"-Bdynamic"|"--gc-sections") {
        } else if a.strip_prefix("--threads=").and_then(|n|n.parse::<usize>().ok()).is_some_and(|n| (1..=32).contains(&n)) {
        } else if Path::new(a).is_absolute() {
            if Path::new(a).file_name().is_some_and(|n|n=="symbols.o") {
                if sym.replace(PathBuf::from(a)).is_some() { return None }
                value=b"<rustc-undefined-table>";
            }
        } else { return fail("bypass-cli") }
        part(&mut h,value);
    }
    if !pie { return fail("bypass-not-pie") }
    let (symbols,raw,resolution,output)=(sym?,raw?,res?,out?);
    let tmp=symbols.parent()?;
    if tmp.parent()!= output.parent() || raw.parent()!=Some(tmp) || tmp.canonicalize().ok()?!=tmp ||
        !tmp.file_name()?.to_str()?.strip_prefix("rustc").is_some_and(|s|s.len()==6&&s.bytes().all(|b|b.is_ascii_alphanumeric())) { return fail("bypass-temp") }
    Some(Config{root,output,symbols,raw,resolution,args_digest:*h.finalize().as_bytes()})
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct Stamp(u64,u64,i64,i64,i64,i64,u64);
impl Stamp {
    pub(crate) fn get(m:&Metadata)->Self { Self(m.dev(),m.ino(),m.ctime(),m.ctime_nsec(),m.mtime(),m.mtime_nsec(),m.len()) }
}
#[derive(Debug)]
pub(crate) struct Snapshot {
    pub(crate) bytes: Vec<u8>,
    pub(crate) stamp: Stamp,
    pub(crate) digest: [u8;32],
}
impl Snapshot {
    pub(crate) fn read(mut f:&File, path:&Path)->io::Result<Self> {
        let old=f.metadata()?;
        if !old.is_file() { return Err(io::Error::other("nonregular observed input")) }
        let stamp=Stamp::get(&old); let mut bytes=Vec::with_capacity(old.len().try_into().map_err(io::Error::other)?);
        f.read_to_end(&mut bytes)?;
        if bytes.len() as u64!=old.len() || Stamp::get(&f.metadata()?)!=stamp || Stamp::get(&std::fs::metadata(path)?)!=stamp {
            return Err(io::Error::other("native input changed during acquisition"))
        }
        let digest=*blake3::hash(&bytes).as_bytes(); Ok(Self{bytes,stamp,digest})
    }
}
fn safe_script(commands:&[Command<'_>])->bool {
    commands.iter().all(|c|match c {
        Command::Arg(_)|Command::OutputFormat(_)=>true,
        Command::Group(xs)|Command::AsNeeded(xs)=>safe_script(xs),
        _=>false,
    })
}
fn symbol_object(bytes: &[u8]) -> bool {
    // rustc's ELF writer encodes undefined Text and Data with STT_NOTYPE. Re-emit
    // its complete object from just these names. This also excludes files which
    // could embed the generated input path, such as DSOs or STT_FILE/debug data.
    let Ok(input) = object::File::parse(bytes) else { return false };
    if input.format() != object::BinaryFormat::Elf || input.kind() != object::ObjectKind::Relocatable
        || input.architecture() != object::Architecture::X86_64 || !input.is_little_endian()
        || !input.is_64() || input.symbols().next().is_none()
    {
        return false;
    }
    let mut output = object::write::Object::new(
        object::BinaryFormat::Elf, object::Architecture::X86_64, object::Endianness::Little,
    );
    output.flags = object::FileFlags::Elf { os_abi: object::elf::OsAbi(0), abi_version: 0, e_flags: object::elf::FileFlags(0) };
    let note = output.add_section(Vec::new(), b".note.gnu.property".to_vec(), object::SectionKind::Note);
    const NOTE: [u8; 32] = [
        4, 0, 0, 0, 16, 0, 0, 0, 5, 0, 0, 0, 71, 78, 85, 0,
        2, 0, 0, 192, 4, 0, 0, 0, 3, 0, 0, 0, 0, 0, 0, 0,
    ];
    output.append_section_data(note, &NOTE, 8);
    for symbol in input.symbols() {
        let Ok(name) = symbol.name_bytes() else { return false };
        if name.is_empty() || !symbol.is_undefined() || symbol.address() != 0 || symbol.size() != 0
            || !matches!(symbol.flags(), object::SymbolFlags::Elf { st_info: object::elf::SymbolInfo(0x10), st_other: object::elf::SymbolOther(0) })
        {
            return false;
        }
        output.add_symbol(object::write::Symbol {
            name: name.to_vec(), value: 0, size: 0, kind: object::SymbolKind::Text,
            scope: object::SymbolScope::Unknown, weak: false,
            section: object::write::SymbolSection::Undefined, flags: object::SymbolFlags::None,
        });
    }
    output.write().is_ok_and(|generated| bytes == generated)
}
fn normalized<'a>(p:&'a Path,c:&Config)->&'a[u8] {
    if p==c.symbols {b"<rustc-undefined-table>"} else {path_bytes(p)}
}
fn add_ref(h:&mut blake3::Hasher, r:InputRef<'_>, c:&Config) {
    part(h,normalized(r.file.filename,c));part(h,normalized(r.file.original_filename,c));
    if let Some(e)=r.entry {number(h,e.start_offset);number(h,e.end_offset);part(h,e.identifier.as_slice());} else {part(h,b"<direct>");}
}
struct Candidate { witness:PathBuf, old_digest:[u8;32] }
pub(crate) fn prepare<P:Platform,F:FileSystem>(loader:&FileLoader<'_,F>,args:&P::Args,groups:&[ResolvedGroup<'_,P>],plugin:bool)->Option<Vec<u8>> {
    let c=config()?;
    if plugin || WARNING.load(Ordering::Relaxed) { return fail("bypass-plugin-warning") }
    let mut h=blake3::Hasher::new();part(&mut h,&c.args_digest);number(&mut h,args.common().available_threads.get());
    // The reported input list comes from the *current* real recursive Wild search. Every byte,
    // including all dormant archive entries and their raw names and symbol index, is captured.
    let mut valid_symbol=false;
    for i in &loader.loaded_files {
        let s=i.storage()?; let data=s.bytes(); let k=FileKind::identify_bytes(data,false).ok()?;
        if !matches!(k,FileKind::ElfObject|FileKind::ElfDynamic|FileKind::Archive|FileKind::Text) {return fail("bypass-kind")}
        if i.filename==c.symbols {
            if valid_symbol || i.original_filename!=c.symbols || !symbol_object(data) {return fail("bypass-symbol-shape")}
            valid_symbol=true;
        } else if i.filename.starts_with(c.symbols.parent()?) {return fail("bypass-temp-consumed")}
        part(&mut h,normalized(&i.filename,c));part(&mut h,normalized(&i.original_filename,c));
        part(&mut h,format!("{:?}",i.modifiers).as_bytes());
        part(&mut h,&s.acquired_digest()?);
    }
    if !valid_symbol || c.raw.symlink_metadata().ok()?.file_type().is_symlink() || std::fs::read_dir(&c.raw).ok()?.next().is_some() {return fail("bypass-raw-dir")}
    let gm=c.resolution.symlink_metadata().ok()?;if !gm.is_file() || gm.len()!=0 {return fail("bypass-gcc-file")}
    // Record actual worker-specific group boundaries, selection and section/symbol ranges,
    // including unresolved members, before deciding to replace section resolution/layout.
    for g in groups {
        part(&mut h,b"group"); number(&mut h,g.files.len());
        for f in &g.files {
            match f {
                ResolvedFile::Object(x)=>{part(&mut h,b"O");add_ref(&mut h,x.common.input,c);number(&mut h,x.common.symbol_id_range.len());number(&mut h,x.section_id_range.len());}
                ResolvedFile::Dynamic(x)=>{part(&mut h,b"D");add_ref(&mut h,x.common.input,c);}
                ResolvedFile::NotLoaded(x)=>{part(&mut h,b"N");number(&mut h,x.symbol_id_range.len());number(&mut h,x.section_id_range.len());}
                ResolvedFile::LinkerScript(x)=>{part(&mut h,b"S");add_ref(&mut h,x.input,c);}
                ResolvedFile::Prelude(_)=>part(&mut h,b"P"),
                ResolvedFile::SyntheticSymbols(_)=>part(&mut h,b"Y"),
                _=>return fail("bypass-group"),
            }
        }
    }
    let old=read_existing(&c.output)?;
    let key=h.finalize().to_hex().to_string();let witness=c.root.join(key);
    let mut f=OpenOptions::new().read(true).custom_flags(libc::O_NOFOLLOW|libc::O_NONBLOCK).open(&witness).ok();
    let valid=f.as_mut().is_some_and(|file|{
        let Ok(m)=file.metadata() else {return false}; if !m.is_file()||m.len()!=32||m.uid()!=unsafe{libc::geteuid()}||m.mode()&0o077!=0{return false}
        let mut d=[0;32];file.read_exact(&mut d).is_ok() && d==old.digest
    });
    CANDIDATE.set(Candidate{witness,old_digest:old.digest}).ok()?;
    if valid && Stamp::get(&c.output.symlink_metadata().ok()?)==old.stamp {event("hit");Some(old.bytes)} else {event("full-train");None}
}
fn read_existing(p:&Path)->Option<Snapshot>{
    let f=OpenOptions::new().read(true).custom_flags(libc::O_NOFOLLOW|libc::O_NONBLOCK).open(p).ok()?;
    let m=f.metadata().ok()?;if !m.is_file() || m.nlink()!=1 || m.uid()!=unsafe{libc::geteuid()} {return None}
    Snapshot::read(&f,p).ok()
}
pub(crate) fn can_train()->bool{CANDIDATE.get().is_some()}
pub(crate) fn output_produced(bytes:&[u8]) { if can_train(){let _=PRODUCED.set(*blake3::hash(bytes).as_bytes());} }
pub(crate) fn commit() {
    let (Some(k),Some(raw))=(CANDIDATE.get(),PRODUCED.get()) else {return};
    if WARNING.load(Ordering::Relaxed) || *raw!=k.old_digest {return}
    // Only admit a steady full output: it already equalled its own prior raw visible file.
    let tmp=k.witness.with_extension(format!("pending.{}",std::process::id()));
    if let Ok(mut f)=OpenOptions::new().write(true).create_new(true).mode(0o600).open(&tmp){
        if f.write_all(raw).and_then(|()|f.sync_data()).is_ok(){let _=std::fs::rename(&tmp,&k.witness);}
        let _=std::fs::remove_file(tmp);
    }
}
pub(crate) fn permit_scripts<P:Platform>(loaded:&crate::input_data::LoadedInputs<'_,P>)->bool {
    loaded.lto_objects.is_empty() && loaded.stub_libraries.is_empty() && loaded.linker_scripts.iter().all(|x|safe_script(&x.script.commands))
}
