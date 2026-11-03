"""Build the bounded source diagnostic on top of the same full-emission donor acquisition."""
from pathlib import Path
import shutil
import prepare_source as base

def apply(src):
    original=base.prepare(src)
    pub=src/'libwild/src'
    shutil.copyfile(Path(__file__).with_name('reuse.rs'),pub/'reuse.rs')
    lib=pub/'lib.rs';writer=pub/'file_writer.rs';args=pub/'args.rs'
    entry=src/'wild/src/main.rs'
    base.rep(entry,'fn main() {','fn main() {\n    libwild::qa_route_other_target();')
    base.rep(lib,'mod frozen;','''mod frozen;
/// Keep every other linker invocation on the exact distributed image.
pub fn qa_route_other_target() {
    if !frozen::active() {
        use std::os::unix::process::CommandExt as _;
        let mut argv=std::env::args_os();
        let argv0=argv.next().expect("linker argv[0]");
        let error=std::process::Command::new(concat!(env!("WILD_QA_ROOT"),"/qa-diagnostic-build/original"))
            .arg0(argv0).args(argv).exec();
        panic!("the attested stock linker could not execute: {error}");
    }
}''')

    base.rep(lib,'mod frozen;','mod frozen;\nmod reuse;')
    base.rep(args,'    eprintln!("{warning}");','''    if crate::frozen::active() {crate::frozen::log(format_args!("WARNING\\t{warning}"));}
    eprintln!("{warning}");''')
    base.rep(lib,'            crate::frozen::context();','            crate::frozen::context();\n            crate::reuse::normalized_environment();')
    anchor='        let mut output = file_writer::Output::new::<P>(args, output_kind, self.file_system.clone());'
    base.rep(lib,anchor,anchor+'''
        if crate::frozen::active() {
            let common=args.common();
            let scripts_only=loaded.linker_scripts.iter().all(|s|crate::reuse::input_script(&s.script.commands));
            let mut tmp_files=file_loader.loaded_files.iter().filter(|s|s.filename.file_name().is_some_and(|n|n=="symbols.o"));
            let symbols_ok=tmp_files.next().is_some_and(|f|f.storage().is_some_and(|s|crate::reuse::symbols_only(s.bytes()))) && tmp_files.next().is_none();
            let temp_root=std::env::args().nth(36).map(std::path::PathBuf::from);
            let temp_root=temp_root.as_deref().and_then(|p|p.parent());
            let selected_temp_paths=file_loader.loaded_files.iter().filter(|f|temp_root.is_some_and(|p|f.filename.starts_with(p))).count();
            let regular_inputs=file_loader.loaded_files.iter().all(|f|f.storage().is_some_and(|x|!x.bytes().starts_with(b"!<thin>\\n")));
            let safe=scripts_only && symbols_ok && regular_inputs && selected_temp_paths==1 && loaded.objects.iter().all(Result::is_ok) && loaded.lto_objects.is_empty() &&
                loaded.stub_libraries.is_empty() && plugin.as_ref().is_none_or(|p| !p.is_initialised()) &&
                args.version_script_path().is_none() && args.export_list_path().is_none() &&
                args.dependency_file().is_none() && !args.should_write_trace_file() &&
                !common.write_layout && !common.write_trace && !common.validate_output &&
                !common.verify_allocation_consistency && !common.verbose && common.unrecognized_options.is_empty() &&
                common.print_allocations.is_none() && common.sym_info.is_none() && common.debug_fuel.is_none() &&
                common.time_phase_options.is_none() && common.numeric_experiments.is_empty() &&
                common.file_replacement_mode.is_none() && common.file_write_mode.is_none() && output.publishes_new();
            crate::frozen::log(format_args!("DOMAINS\\t{}\\t{}\\t{}",scripts_only,symbols_ok,selected_temp_paths));
            crate::frozen::log(format_args!("TYPED\\t{}\\t{}\\t{}\\t{}\\t{}\\t{:?}\\t{}",
                loaded.objects.len(),loaded.linker_scripts.len(),loaded.stub_libraries.len(),loaded.lto_objects.len(),
                common.available_threads,common.files_per_group,output.publishes_new()));
            FRESH_APPLICATION
        }'''.replace('all(Result::is_ok)','all(|entry| entry.is_ok())'))
    base.rep(lib,'            FRESH_APPLICATION',Path(__file__).with_name('fresh_output.inc').read_text().rstrip())
    fs=pub/'fs.rs'
    create='        let file = match open_options.read(true).write(true).create(true).open(&path) {'
    base.rep(fs,create,'''        let fresh=crate::reuse::fresh_creation();
        if fresh {
            crate::reuse::before_fresh_open(&path)?;
            open_options.create_new(true);
        }
'''+create)
    err="                // Retry open operation with UnlinkAndReplace if it's an ETXTBSY error and"
    base.rep(fs,err,'''                if fresh {crate::reuse::record_collision(&error);return Err(error.into());}
'''+err)
    branch='if options.file_replacement_mode == FileReplacementMode::UpdateInPlaceWithFallback {'
    base.rep(fs,branch,'if !fresh && options.file_replacement_mode == FileReplacementMode::UpdateInPlaceWithFallback {')
    start='        let huge_pages_required = options.madvise_huge_pages == Some(true);'
    base.rep(fs,start,'''        if fresh {crate::reuse::record_fresh_file(&file)?;}
'''+start)
    grouping=pub/'grouping.rs';g=grouping.read_text()
    for name in ('determine_symbols_per_group','determine_max_files_per_group'):
        start='fn '+name+'(';assert g.count(start)==1;g=g.replace(start,'pub(crate) '+start)
    start='        if finish_group {\n            num_symbols_in_group = 0;'
    assert g.count(start)==1;g=g.replace(start,'''        if finish_group {
            if crate::frozen::active(){crate::frozen::log(format_args!("ACTUAL-GROUP\\t{}\\t{}",group_objects.len(),num_symbols_in_group));}
            num_symbols_in_group = 0;''')
    grouping.write_text(g)
    group_source=Path(__file__).with_name('group_input.inc').read_text()
    base.rep(lib,'            let safe=scripts_only',group_source+'            let safe=current_group_input.is_some() && scripts_only')
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
    return list(dict.fromkeys(original+['wild/src/main.rs']+['libwild/src/'+p for p in ('file_writer.rs','args.rs','reuse.rs','grouping.rs')]))
