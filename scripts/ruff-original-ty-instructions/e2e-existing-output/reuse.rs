//! Narrow single-link research gate. The private coordinator knows the receipt from the previous
//! full Cargo invocation. The program rereads both native inputs and the existing executable.
use std::fs::File;
use std::io::{Read as _, Write as _};
use std::os::unix::fs::{FileExt as _, MetadataExt as _, OpenOptionsExt as _};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

fn state() -> PathBuf {
    Path::new(env!("WILD_QA_ROOT")).join("native-donor-state")
}

fn notice(name: &str, bytes: &[u8]) -> std::io::Result<()> {
    let target = state().join(name);
    let staging = target.with_extension("pending");
    let mut f = File::create_new(&staging)?;
    f.write_all(bytes)?;
    drop(f);
    std::fs::rename(staging, target)
}

fn image() -> Option<String> {
    // No externally mutable code-generating DSO is eligible. The standalone GNU static
    // image is protected while running by normal Linux executable write exclusion.
    let maps = std::fs::read_to_string("/proc/self/maps").ok()?;
    let executable = std::fs::read_link("/proc/self/exe").ok()?;
    let mut image_code = false;
    for line in maps.lines() {
        let cols: Vec<_> = line.split_ascii_whitespace().collect();
        if cols.len() < 2 { return None; }
        if cols[1].contains('x') {
            if cols.len() != 6 { return None; }
            let name = cols[5];
            if name == "[vdso]" || name == "[vsyscall]" {continue;}
            if Path::new(name) != executable { return None; }
            image_code = true;
        }
    }
    if !image_code { return None; }
    let mut f=File::open("/proc/self/exe").ok()?;
    if f.metadata().ok()?.len() > 32<<20 {return None;}
    let mut hash=blake3::Hasher::new();
    let mut block=[0;32768];
    loop {
        let n=f.read(&mut block).ok()?;
        if n==0 {break;}
        hash.update(&block[..n]);
    }
    Some(hash.finalize().to_string())
}

pub(crate) fn request(output: &Path, eligible: bool) -> std::io::Result<Option<(Vec<u8>,File)>> {
    use crate::frozen::log;
    let image = image();
    let forbidden = std::env::vars_os().any(|(k,_)| k.to_str().is_none_or(|k| k.starts_with("WILD_") ||
        matches!(k,"LD_PRELOAD"|"LD_AUDIT"|"LD_DEBUG"|"LD_PROFILE"|"GLIBC_TUNABLES")));
    log(format_args!("ADMISSION\t{}\t{}",eligible && !forbidden,image.as_deref().unwrap_or("dynamic-or-unknown")));
    if !state().join("coordinate").is_file() {return Ok(None);}
    let id = std::process::id();
    if state().join("stock-reference").is_file() {
        use std::os::unix::fs::OpenOptionsExt as _;
        let path=state().join(format!("local-env-{id}"));
        let mut raw=std::fs::OpenOptions::new().create_new(true).write(true).mode(0o600).open(path)?;
        for (key,value) in std::env::vars_os() {
            raw.write_all(key.as_encoded_bytes())?;raw.write_all(b"=")?;
            raw.write_all(value.as_encoded_bytes())?;raw.write_all(b"\0")?;
        }
        drop(raw);
    }
    notice(&format!("ready-{id}"),b"complete\n")?;
    let response = state().join(format!("answer-{id}"));
    let deadline = Instant::now()+Duration::from_secs(120);
    while !response.is_file() {
        if Instant::now()>deadline {log(format_args!("MISS\tcoordinator-timeout"));return Ok(None);}
        std::thread::sleep(Duration::from_millis(2));
    }
    let action = std::fs::read_to_string(response)?;
    if action=="full\n" {log(format_args!("MISS\tcoordinator-full"));return Ok(None);}
    let mut parts=action.split_ascii_whitespace();
    let attempt=parts.next()==Some("verify");
    let expected=parts.next().and_then(|x|blake3::Hash::from_hex(x).ok());
    let Some(size)=parts.next().and_then(|x|x.parse::<usize>().ok()) else {return Ok(None);};
    if !attempt || !eligible || forbidden || image.is_none() || parts.next().is_some() ||
        expected.is_none() || size<1<<20 || size>250<<20 {log(format_args!("MISS\tconditions"));return Ok(None);}
    let started=Instant::now();
    let before=match std::fs::symlink_metadata(output) {Ok(x) => x, Err(_) => return Ok(None)};
    if !before.is_file() || before.nlink()!=1 || before.len()!=size as u64 || before.mode()&0o111==0 {
        log(format_args!("MISS\toutput-noncanonical"));return Ok(None);
    }
    let file=match std::fs::OpenOptions::new().read(true).custom_flags(libc::O_NONBLOCK|libc::O_NOFOLLOW|libc::O_CLOEXEC).open(output){Ok(x)=>x,Err(_)=>return Ok(None)};
    let stamp=crate::frozen::stamp(&before);
    if stamp!=crate::frozen::stamp(&file.metadata()?) {log(format_args!("MISS\topen-generation"));return Ok(None);}
    let mut bytes=vec![0;size];
    let split=size/2;
    if file.read_exact_at(&mut bytes[..split],0).is_err() {log(format_args!("MISS\tshort-output"));return Ok(None);}
    if state().join("mid-output").is_file() {
        notice("output-half", output.as_os_str().as_encoded_bytes())?;
        let until=Instant::now()+Duration::from_secs(15);
        while !state().join("output-continue").is_file() {
            if Instant::now()>until{return Ok(None);}
            std::thread::sleep(Duration::from_millis(2));
        }
    }
    if file.read_exact_at(&mut bytes[split..],split as u64).is_err() ||
        Some(blake3::hash(&bytes))!=expected ||
        std::fs::symlink_metadata(output).ok().is_none_or(|m|stamp!=crate::frozen::stamp(&m)) ||
        stamp!=crate::frozen::stamp(&file.metadata()?) {
        log(format_args!("MISS\toutput-bytes-or-generation"));return Ok(None);
    }
    log(format_args!("ACCEPT\t{}\t{}\t{}\t{}\t{}",before.dev(),before.ino(),size,expected.unwrap(),started.elapsed().as_nanos()));
    Ok(Some((bytes,file)))
}

pub(crate) fn normalized_environment() {
    // Keep all environment entries. Only canonicalize the two exact compiler nonce paths
    // in GCC's serialized argv, which Wild's native no-plugin branch does not interpret.
    let args:Vec<_>=std::env::args().collect();
    let Some(symbol)=args.get(36).and_then(|x|Path::new(x).parent()).and_then(|x|x.to_str())else{return};
    let Some(res)=args.get(4).and_then(|x|x.strip_prefix("-plugin-opt=-fresolution="))else{return};
    let mut names: Vec<_>=std::env::vars_os().collect();
    names.sort();
    for (name,value) in names {
        let n=name.to_str().unwrap_or("");
        let bytes=value.as_encoded_bytes();
        let normalized;
        let use_bytes=if n=="COLLECT_GCC_OPTIONS" {
            let Some(v)=value.to_str()else{return};
            normalized=v.replace(symbol,"<rustc-tmp>").replace(res,"<unused-lto-res>");
            normalized.as_bytes()
        }else{bytes};
        crate::frozen::log(format_args!("ENVKEY\t{name:?}\t{}",blake3::hash(use_bytes)));
    }
}


pub(crate) fn input_script(commands: &[crate::linker_script::Command<'_>]) -> bool {
    use crate::linker_script::Command;
    commands.iter().all(|c| match c {
        Command::Arg(_) | Command::Ignored | Command::OutputFormat(_) => true,
        Command::AsNeeded(nested) | Command::Group(nested) => input_script(nested),
        _ => false,
    })
}

pub(crate) fn symbols_only(bytes: &[u8]) -> bool {
    // Restrict the changing path to a relocatable with only the GNU property, symbols
    // and strings. No symbol defines bytes, references a file name, or has provenance
    // in any input section. Its whole content still participates in the recipe.
    fn inspect(b: &[u8]) -> Option<()> {
        let u16at=|b:&[u8],i| Some(u16::from_le_bytes(b.get(i..i+2)?.try_into().ok()?));
        let u32at=|b:&[u8],i| Some(u32::from_le_bytes(b.get(i..i+4)?.try_into().ok()?));
        let u64at=|b:&[u8],i| Some(u64::from_le_bytes(b.get(i..i+8)?.try_into().ok()?));
        if b.len()>1<<20 || b.get(..7)?!=b"\x7fELF\x02\x01\x01" || u16at(b,16)?!=1 || u16at(b,18)?!=62 ||
            u16at(b,56)?!=0 || u16at(b,58)?!=64 || u16at(b,60)?!=5 || u16at(b,62)?!=4 {return None;}
        let shoff:usize=u64at(b,40)?.try_into().ok()?;
        let sh=b.get(shoff..shoff.checked_add(5*64)?)?;
        if sh[..64].iter().any(|&v|v!=0) {return None;}
        let region=|r:&[u8]| {
            let off:usize=u64at(r,24)?.try_into().ok()?;
            let size:usize=u64at(r,32)?.try_into().ok()?;
            b.get(off..off.checked_add(size)?)
        };
        let names=region(&sh[4*64..5*64])?;
        let strs=region(&sh[3*64..4*64])?;
        let section_names:[&[u8];4]=[b".note.gnu.property",b".symtab",b".strtab",b".shstrtab"];
        for (i,(r,n)) in sh[64..].chunks_exact(64).zip(section_names).enumerate() {
            let off=u32at(r,0)? as usize;
            if names.get(off..)?.split(|x|*x==0).next()?!=n || u32at(r,4)?!=[7,2,3,3][i] ||
                u64at(r,8)?!=0 || region(r).is_none() {return None;}
        }
        let property=region(&sh[64..128])?;
        if property.len()!=32 || u32at(property,0)?!=4 || u32at(property,4)?!=16 || u32at(property,8)?!=5 ||
            &property[12..16]!=b"GNU\0" || u32at(property,16)?!=0xc0000002 || u32at(property,20)?!=4 ||
            u32at(property,24)?!=3 || u32at(property,28)?!=0 {return None;}
        let tab=&sh[2*64..3*64];let syms=region(tab)?;
        if u32at(tab,40)?!=3 || u32at(tab,44)?!=1 || u64at(tab,56)?!=24 || syms.len()<48 ||
            !syms.len().is_multiple_of(24) || syms[..24].iter().any(|x|*x!=0) ||
            strs.first()!=Some(&0) || strs.last()!=Some(&0) {return None;}
        for sym in syms[24..].chunks_exact(24) {
            let name=u32at(sym,0)? as usize;
            if name==0 || name>=strs.len() || sym[4]!=16 || sym[5..].iter().any(|x|*x!=0) {return None;}
        }
        Some(())
    }
    inspect(bytes).is_some()
}

// One link runs in this process. The background writer needs the same exclusive-create guard.
static FRESH:std::sync::atomic::AtomicBool=std::sync::atomic::AtomicBool::new(false);
static COLLISION:std::sync::atomic::AtomicBool=std::sync::atomic::AtomicBool::new(false);
static CREATED:std::sync::OnceLock<(u64,u64)>=std::sync::OnceLock::new();
pub(crate) fn start_fresh_creation(){
    assert!(!FRESH.swap(true,std::sync::atomic::Ordering::SeqCst));
}
pub(crate) fn fresh_creation()->bool{FRESH.load(std::sync::atomic::Ordering::SeqCst)}
pub(crate) fn record_collision(err:&std::io::Error){
    if err.kind()==std::io::ErrorKind::AlreadyExists {
        COLLISION.store(true,std::sync::atomic::Ordering::SeqCst);
    }
}
pub(crate) fn record_fresh_file(file:&File)->std::io::Result<()>{
    let st=file.metadata()?;
    CREATED.set((st.dev(),st.ino())).map_err(|_|std::io::Error::other("too many output generations"))?;
    Ok(())
}
pub(crate) fn finish_fresh_creation()->bool{
    assert!(FRESH.swap(false,std::sync::atomic::Ordering::SeqCst));
    COLLISION.load(std::sync::atomic::Ordering::SeqCst)
}
pub(crate) fn before_fresh_open(path:&Path)->std::io::Result<()>{
    if !state().join("exclusive-witness").exists(){return Ok(());}
    notice("fresh-opening", path.as_os_str().as_encoded_bytes())?;
    let limit=Instant::now()+Duration::from_secs(25);
    while !state().join("fresh-continue").exists(){
        if Instant::now()>limit{return Err(std::io::Error::other("new output collision witness timed out"));}
        std::thread::sleep(Duration::from_millis(2));
    }
    Ok(())
}
pub(crate) fn published_new_generation(donor:&File,path:&Path)->std::io::Result<bool>{
    let old=donor.metadata()?;
    let Some((dev,ino))=CREATED.get().copied()else{return Ok(false)};
    let curr=match std::fs::symlink_metadata(path){Ok(m)=>m,Err(_)=>return Ok(false)};
    crate::frozen::log(format_args!("FRESH-GENERATIONS\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}",
        old.dev(),old.ino(),old.len(),old.blocks(),old.nlink(),dev,ino,curr.dev(),curr.ino()));
    Ok((old.dev(),old.ino())!=(dev,ino) && old.nlink()==0 && (curr.dev(),curr.ino())==(dev,ino)
        && curr.is_file() && curr.nlink()==1 && curr.len()==old.len())
}
