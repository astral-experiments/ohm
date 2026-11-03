"""Build the bounded source diagnostic on top of the same full-emission donor acquisition."""
from pathlib import Path
import shutil
import prepare_source as base

def apply(src):
    original=base.prepare(src)
    pub=src/'libwild/src'
    shutil.copyfile(Path(__file__).with_name('reuse.rs'),pub/'reuse.rs')
    lib=pub/'lib.rs';writer=pub/'file_writer.rs';args=pub/'args.rs'
    base.rep(lib,'mod frozen;','mod frozen;\nmod reuse;')
    base.rep(args,'    eprintln!("{warning}");','''    if crate::frozen::active() {crate::frozen::log(format_args!("WARNING\\t{warning}"));}
    eprintln!("{warning}");''')
    base.rep(lib,'            crate::frozen::context();','            crate::frozen::context();\n            crate::reuse::normalized_environment();')
    anchor='        let mut output = file_writer::Output::new::<P>(args, output_kind, self.file_system.clone());'
    base.rep(lib,anchor,anchor+'''
        if crate::frozen::active() {
            let common=args.common();
            let safe=loaded.objects.iter().all(Result::is_ok) && loaded.lto_objects.is_empty() &&
                loaded.stub_libraries.is_empty() && plugin.as_ref().is_none_or(|p| !p.is_initialised()) &&
                args.version_script_path().is_none() && args.export_list_path().is_none() &&
                args.dependency_file().is_none() && !args.should_write_trace_file() &&
                !common.write_layout && !common.write_trace && !common.validate_output &&
                !common.verify_allocation_consistency && !common.verbose && common.unrecognized_options.is_empty() &&
                common.print_allocations.is_none() && common.sym_info.is_none() && common.debug_fuel.is_none() &&
                common.time_phase_options.is_none() && common.numeric_experiments.is_empty() &&
                common.file_replacement_mode.is_none() && common.file_write_mode.is_none() && output.publishes_new();
            crate::frozen::log(format_args!("TYPED\\t{}\\t{}\\t{}\\t{}\\t{}\\t{:?}\\t{}",
                loaded.objects.len(),loaded.linker_scripts.len(),loaded.stub_libraries.len(),loaded.lto_objects.len(),
                common.available_threads,common.files_per_group,output.publishes_new()));
            if let Some(bytes)=crate::reuse::request(args.output(),safe)? {
                let start=std::time::Instant::now();
                output.set_size(bytes.len() as u64);
                output.with_output_bytes(|s|{s.out.copy_from_slice(&bytes);Ok(())})?;
                crate::frozen::log(format_args!("FRESH-PUBLISH\\t{}\\t{}",bytes.len(),start.elapsed().as_nanos()));
                return Ok(LinkerOutput::empty());
            }
        }'''.replace('all(Result::is_ok)','all(|entry| entry.is_ok())'))
    start='        let mut sized_output = match &self.creator {'
    base.rep(writer,start,'''        self.with_output_bytes(|out|write_fn(out, layout))
    }

    pub(crate) fn publishes_new(&self) -> bool {
        matches!(&self.creator,FileCreator::Regular{..}) ||
            self.config.file_replacement_mode == FileReplacementMode::UnlinkAndReplace
    }

    pub(crate) fn with_output_bytes(&self, write_fn: impl FnOnce(&mut SizedOutput<F::Output>)->Result) -> Result {
'''+start)
    base.rep(writer,'        write_fn(&mut sized_output, layout)?;','        write_fn(&mut sized_output)?;')
    return list(dict.fromkeys(original+['libwild/src/'+p for p in ('file_writer.rs','args.rs','reuse.rs')]))
