"""Attach the diagnostic to the frozen upstream source, performing zero output reuse."""
import shutil
from pathlib import Path
import subprocess
HERE=Path(__file__).resolve().parent
BASE='e856d81f6683cad80b9fe0ebf1a0c3c403c6fe11'
def rep(path,left,right):
    text=path.read_text()
    assert text.count(left)==1,(path,left)
    path.write_text(text.replace(left,right))
def prepare(src):
    src=Path(src);run=lambda *a:subprocess.check_output(['git','-C',src,*a],text=True).strip()
    assert run('rev-parse','HEAD')==BASE and not run('status','--porcelain')
    return apply_diagnostic(src)

def apply_diagnostic(src):
    # Keep the same source-positioned resolver events that independently matched all 94 kernel misses.
    patch=HERE.parent/'e2e-wild-inputs/lookup-diagnostic.patch'
    subprocess.run(['git','-C',src,'apply',patch],check=True)
    path=src/'libwild/src';f=path/'fs.rs';load=path/'input_data.rs';lib=path/'lib.rs'
    for p in (f,load):
        text=p.read_text();assert 'eprintln!("OHMLOOK' in text
        # Wrap only the pre-existing diagnostic macros, retaining their literal complete values.
        p.write_text(text.replace('eprintln!("OHMLOOK', 'crate::frozen_lookup!("OHMLOOK'))
    shutil.copyfile(HERE/'frozen.rs',path/'frozen.rs')
    starter='pub(crate) mod fs;';rep(lib,starter,'''mod frozen;
#[macro_export]
macro_rules! frozen_lookup {
    ($($arg:tt)*) => { if crate::frozen::active() { crate::frozen::log(format_args!($($arg)*)); } };
}
'''+starter)
    rep(f,'#[derive(Debug)]\npub struct OsInputFile {\n    bytes: crate::host::fs::InputBytes,','''#[derive(Debug)]
enum Backing {
    Ordinary(crate::host::fs::InputBytes),
    Frozen(Box<[u8]>, Arc<File>, crate::frozen::Stamp),
}
#[derive(Debug)]
pub struct OsInputFile {
    bytes: Backing,''')
    rep(f,'        &self.bytes\n    }\n\n    fn verify_unchanged','''        match &self.bytes {
            Backing::Ordinary(bytes) => bytes,
            Backing::Frozen(bytes, _, _) => bytes,
        }
    }

    fn verify_unchanged''')
    rep(f,'Ok(std::fs::metadata(&self.path)?.modified()? == self.modification_time)','''if let Backing::Frozen(_, handle, old) = &self.bytes {
            let same = old == &crate::frozen::stamp(&handle.metadata()?) &&
                old == &crate::frozen::stamp(&std::fs::metadata(&self.path)?);
            if !same {
                crate::frozen::log(format_args!("REFUSED\\tchanged-before-return\\t{}", self.path.display()));
            }
            return Ok(same);
        }
        Ok(std::fs::metadata(&self.path)?.modified()? == self.modification_time)''')
    rep(f,'        crate::host::fs::release_input_memory(&self.bytes);','''        if let Backing::Ordinary(data) = &self.bytes {
            crate::host::fs::release_input_memory(data);
        }''')
    rep(f,'        let bytes = crate::host::fs::read_input(&file, path, prepopulate_maps)?;', '''        let file = Arc::new(file);
        let bytes = if crate::frozen::active() {
            let (bytes, stamp) = crate::frozen::snapshot(&file, path)?;
            Backing::Frozen(bytes, Arc::clone(&file), stamp)
        } else {
            Backing::Ordinary(crate::host::fs::read_input(&file, path, prepopulate_maps)?)
        };''')
    rep(f,'            Some(Arc::new(file)),','            Some(file),')
    rep(f,'        let file_write_mode = options.write_mode.unwrap_or(defaults.write_mode);','''        let file_write_mode = if crate::frozen::active() {
            if options.write_mode.is_some() || options.madvise_huge_pages.is_some() {
                bail!("outside diagnostic output flags");
            }
            FileWriteMode::BufferThenWrite
        } else {
            options.write_mode.unwrap_or(defaults.write_mode)
        };''')
    rep(f,'    fn finish(mut self) -> Result {\n        if let OsOutputBuffer', '''    fn finish(mut self) -> Result {
        if crate::frozen::active() {
            use std::os::unix::fs::MetadataExt as _;
            assert!(matches!(self.buffer, OsOutputBuffer::InMemory(_)), "training needs a private emitted buffer");
            let meta = self.file.metadata()?;
            crate::frozen::log(format_args!("EMITTED\\t{}\\t{}\\t{}\\t{}\\t{}", meta.dev(),meta.ino(),
                                          self.bytes().len(), blake3::hash(self.bytes()),self.path.display()));
        }
        if let OsOutputBuffer''')
    rep(lib, '        let identity = args.common().linker_identity();', '        crate::frozen::entry_gate()?;\n        let identity = args.common().linker_identity();')
    rep(lib,'        let loaded = loaded?;','''        let loaded = loaded?;
        if crate::frozen::active() {
            crate::frozen::context();
            for (i, file) in file_loader.loaded_files.iter().enumerate() {
                let data = file.storage().expect("all inputs must have immutable bytes").bytes();
                crate::frozen::log(format_args!("USED\\t{i}\\t{}\\t{}\\t{:?}\\t{}",
                                data.len(),blake3::hash(data),file.modifiers,file.filename.display()));
            }
        }''')
    rep(lib,'        file_loader.verify_inputs_unchanged()?;','''        file_loader.verify_inputs_unchanged()?;
        if result.is_ok() && crate::frozen::active() {
            crate::frozen::log(format_args!("VERIFIED"));
        }''')
    return ['libwild/src/'+p for p in ('fs.rs','input_data.rs','lib.rs','frozen.rs')]
if __name__=='__main__':
    import sys
    prepare(Path(sys.argv[1]))
