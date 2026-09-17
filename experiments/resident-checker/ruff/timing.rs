#![feature(rustc_private)]

extern crate rustc_ast;
extern crate rustc_driver;
extern crate rustc_hir;
extern crate rustc_interface;
extern crate rustc_middle;

use std::collections::BTreeMap;
use std::io::{self, BufRead, Write};
use std::time::Instant;

use rustc_ast::{LitIntType, LitKind, UintTy};
use rustc_driver::{Callbacks, Compilation};
use rustc_hir::def::DefKind;
use rustc_hir::def_id::LocalDefId;
use rustc_interface::interface;
use rustc_middle::hir::map::OhmResidentScalarTailSnapshot;
use rustc_middle::ty::TyCtxt;

const CASES: &[(&str, &str)] = &[
    ("unicode-identifier", "is_unicode_identifier_start"),
    ("parse-octet", "parse_octet"),
    ("token-set", "at_ts"),
    ("parse-atom", "parse_atom"),
];

fn stdout(line: std::fmt::Arguments<'_>) {
    let mut stream = io::stdout().lock();
    writeln!(stream, "{line}").unwrap();
    stream.flush().unwrap();
}

fn marker(phase: &str, operation: &str, case: &str) {
    let mut stream = io::stderr().lock();
    writeln!(stream, "timing-{phase}\t{operation}\t{case}").unwrap();
    stream.flush().unwrap();
}

fn fresh(tcx: TyCtxt<'_>) {
    let started = Instant::now();
    let _ = rustc_driver::catch_fatal_errors(|| tcx.ensure_ok().analysis(()));
    let elapsed = started.elapsed().as_nanos();
    let errors = tcx.dcx().err_count();
    stdout(format_args!(
        "fresh\t{}\t{elapsed}\t{errors}",
        std::process::id()
    ));
    // Error diagnostics were already emitted. A compiler exit is not the timed endpoint,
    // and clearing it allows the caller to distinguish expected diagnostics from a driver crash.
    tcx.dcx().reset_err_count();
}

fn resident<'tcx>(tcx: TyCtxt<'tcx>) {
    assert!(tcx.query_system.resident.is_some());
    let mut owners: BTreeMap<&str, LocalDefId> = BTreeMap::new();
    for id in tcx.hir_body_owners() {
        if matches!(tcx.def_kind(id), DefKind::Fn | DefKind::AssocFn) {
            let name = tcx.item_name(id.to_def_id()).to_string();
            if let Some(&(case, _)) = CASES.iter().find(|(_, selected)| *selected == name) {
                assert!(owners.insert(case, id).is_none(), "ambiguous owner: {name}");
            }
        }
    }
    assert_eq!(owners.len(), CASES.len());

    marker("start", "baseline", "-");
    let started = Instant::now();
    let _ = rustc_driver::catch_fatal_errors(|| tcx.ensure_ok().analysis(()));
    let elapsed = started.elapsed().as_nanos();
    let errors = tcx.dcx().err_count();
    marker("end", "baseline", "-");
    assert_eq!(errors, 0, "resident baseline must be clean");
    stdout(format_args!("ready\t{}\t{elapsed}", std::process::id()));

    let mut active: Option<(&str, OhmResidentScalarTailSnapshot<'tcx>)> = None;
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        if line == "quit" {
            assert!(active.is_none(), "finish with an unmodified source");
            stdout(format_args!("bye"));
            return;
        }
        let (operation, requested) = line.split_once('\t').expect("operation and case");
        let (&case, &owner) = owners.get_key_value(requested).expect("unknown case");
        assert!(
            matches!(operation, "apply" | "restore"),
            "unknown operation"
        );
        tcx.dcx().reset_err_count();
        marker("start", operation, case);
        let request_started = Instant::now();
        let mutation_started = Instant::now();
        let eviction = match operation {
            "apply" => {
                assert!(
                    active.is_none(),
                    "restore the previous edit before applying another"
                );
                let replacement = LitKind::Int(0u128.into(), LitIntType::Unsigned(UintTy::U8));
                let (snapshot, eviction) = unsafe {
                    tcx.ohm_override_private_scalar_tail(owner, replacement)
                        .expect("preselected source edit must be supported")
                };
                active = Some((case, snapshot));
                eviction
            }
            "restore" => {
                let (original_case, snapshot) = active.take().expect("restore requires an edit");
                assert_eq!(original_case, case);
                unsafe {
                    tcx.ohm_restore_private_scalar_tail(snapshot)
                        .expect("preselected source edit must be restorable")
                }
            }
            _ => unreachable!(),
        };
        let mutation = mutation_started.elapsed().as_nanos();
        let analysis_started = Instant::now();
        let _ = rustc_driver::catch_fatal_errors(|| tcx.ensure_ok().analysis(()));
        let analysis = analysis_started.elapsed().as_nanos();
        let total = request_started.elapsed().as_nanos();
        let errors = tcx.dcx().err_count();
        marker("end", operation, case);
        let expected = usize::from(operation == "apply");
        assert_eq!(
            errors, expected,
            "unexpected diagnostics for {case}/{operation}"
        );
        stdout(format_args!(
            "result\t{operation}\t{case}\t{mutation}\t{analysis}\t{total}\t{errors}\t{}",
            eviction.revision
        ));
    }
    panic!("parent closed stdin without sending quit");
}

struct Driver;

impl Callbacks for Driver {
    fn after_expansion<'tcx>(&mut self, _: &interface::Compiler, tcx: TyCtxt<'tcx>) -> Compilation {
        match std::env::var("OHM_RUFF_TIMING_MODE").as_deref() {
            Ok("resident") => resident(tcx),
            Ok("fresh") => fresh(tcx),
            _ => panic!("OHM_RUFF_TIMING_MODE must be resident or fresh"),
        }
        Compilation::Stop
    }
}

fn main() -> std::process::ExitCode {
    let args = std::env::args().collect::<Vec<_>>();
    rustc_driver::catch_with_exit_code(|| rustc_driver::run_compiler(&args, &mut Driver))
}
