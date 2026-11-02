"""Install the prototype hooks on the exact Wild 0.11.0 source using single-match anchors."""
from pathlib import Path
import sys
root=Path(sys.argv[1])/'libwild/src'
def sub(name,old,new):
    p=root/name; s=p.read_text(); assert s.count(old)==1,(name,old);p.write_text(s.replace(old,new))
sub('lib.rs','pub(crate) mod only_keep_debug;','pub(crate) mod observation_replay;\npub(crate) mod only_keep_debug;')
sub('lib.rs','let loaded = loaded?;','let loaded = loaded?;\n        let eligible_scripts = observation_replay::active() && observation_replay::permit_scripts(&loaded);')
sub('lib.rs','        let layout_rules = layout_rules_builder.build::<P>(args);','''        if eligible_scripts && let Some(bytes) = observation_replay::prepare::<P,F>(
            file_loader, args, &resolver.resolved_groups, plugin.as_ref().is_some_and(|p| p.is_initialised()),
        ) {
            file_loader.verify_inputs_unchanged()?;
            output.publish_proven_bytes(&bytes)?;
            return Ok(LinkerOutput::empty());
        }
        let layout_rules = layout_rules_builder.build::<P>(args);''')
sub('lib.rs','        result\n    }\n\n    pub fn file_system','        if result.is_ok() { observation_replay::commit(); }\n        result\n    }\n\n    pub fn file_system')
sub('args.rs','    eprintln!("{warning}");','    crate::observation_replay::note_warning();\n    eprintln!("{warning}");')
sub('input_data.rs','    original_filename: PathBuf,','    pub(crate) original_filename: PathBuf,')
sub('input_data.rs',"    original_filename: &'data Path,","    pub(crate) original_filename: &'data Path,")
sub('fs.rs','pub trait InputFileData: Send + Sync + std::fmt::Debug {','pub trait InputFileData: Send + Sync + std::fmt::Debug {\n    fn acquired_digest(&self) -> Option<[u8; 32]> { None }')
sub('fs.rs','    bytes: crate::host::fs::InputBytes,','    bytes: Option<crate::host::fs::InputBytes>,\n    snapshot: Option<crate::observation_replay::Snapshot>,')
sub('fs.rs','''impl InputFileData for OsInputFile {
    fn bytes(&self) -> &[u8] {
        &self.bytes
    }''','''impl InputFileData for OsInputFile {
    fn acquired_digest(&self) -> Option<[u8;32]> { self.snapshot.as_ref().map(|s|s.digest) }
    fn bytes(&self) -> &[u8] {
        if let Some(s)=&self.snapshot { &s.bytes } else { self.bytes.as_deref().unwrap() }
    }''')
sub('fs.rs','        Ok(std::fs::metadata(&self.path)?.modified()? == self.modification_time)','''        let now=std::fs::metadata(&self.path)?;
        if let Some(s)=&self.snapshot { return Ok(crate::observation_replay::Stamp::get(&now)==s.stamp) }
        Ok(now.modified()? == self.modification_time)''')
sub('fs.rs','        crate::host::fs::release_input_memory(&self.bytes);','        if let Some(bytes)=&self.bytes { crate::host::fs::release_input_memory(bytes); }')
sub('fs.rs','        let bytes = crate::host::fs::read_input(&file, path, prepopulate_maps)?;','''        let (bytes, snapshot) = if crate::observation_replay::active() {
            (None, Some(crate::observation_replay::Snapshot::read(&file, path)?))
        } else { (Some(crate::host::fs::read_input(&file, path, prepopulate_maps)?),None) };''')
sub('fs.rs','''            OsInputFile {
                bytes,
                path:''','''            OsInputFile {
                bytes, snapshot,
                path:''')
sub('fs.rs','    buffer: OsOutputBuffer,','    buffer: OsOutputBuffer,\n    shadow: Option<Vec<u8>>,')
sub('fs.rs','''    fn bytes(&self) -> &[u8] {
        match &self.buffer''','''    fn bytes(&self) -> &[u8] {
        if let Some(shadow)=&self.shadow { return shadow }
        match &self.buffer''')
sub('fs.rs','''    fn bytes_mut(&mut self) -> &mut [u8] {
        match &mut self.buffer''','''    fn bytes_mut(&mut self) -> &mut [u8] {
        if let Some(shadow)=&mut self.shadow { return shadow }
        match &mut self.buffer''')
sub('fs.rs','''    fn finish(mut self) -> Result {
        if let OsOutputBuffer::InMemory''','''    fn finish(mut self) -> Result {
        if let Some(shadow)=self.shadow.take() {
            crate::observation_replay::output_produced(&shadow);
            match &mut self.buffer {
                OsOutputBuffer::InMemory(raw) => raw.copy_from_slice(&shadow),
                OsOutputBuffer::Mmap(raw) => raw.copy_from_slice(&shadow),
            }
        }
        if let OsOutputBuffer::InMemory''')
sub('fs.rs','        Ok(OsOutputFile { file, buffer, path })','''        let shadow = crate::observation_replay::can_train().then(|| match &buffer {
            OsOutputBuffer::InMemory(data) => data.to_vec(),
            OsOutputBuffer::Mmap(data) => data.to_vec(),
        });
        Ok(OsOutputFile { file, buffer, path, shadow })''')
sub('file_writer.rs','''        let mut sized_output = match &self.creator {''','''        self.write_buffer(|out| write_fn(out,layout))
    }

    pub(crate) fn publish_proven_bytes(&mut self, bytes:&[u8])->Result {
        self.set_size(bytes.len() as u64);
        self.write_buffer(|out| { out.out.copy_from_slice(bytes); Ok(()) })
    }

    fn write_buffer(&self,write:impl FnOnce(&mut SizedOutput<F::Output>)->Result)->Result {
        let mut sized_output = match &self.creator {''')
sub('file_writer.rs','        write_fn(&mut sized_output, layout)?;','        write(&mut sized_output)?;')
