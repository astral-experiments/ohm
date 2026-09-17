#![feature(rustc_private)]

extern crate rustc_ast;
extern crate rustc_driver;
extern crate rustc_hir;
extern crate rustc_interface;
extern crate rustc_middle;

use std::collections::BTreeMap;
use std::sync::{Mutex, OnceLock};

use rustc_ast::{LitIntType, LitKind};
use rustc_driver::{Callbacks, Compilation};
use rustc_hir::def::DefKind;
use rustc_hir::def_id::LocalDefId;
use rustc_hir::intravisit::{self, Visitor};
use rustc_hir::{Expr, ExprKind, HirId};
use rustc_interface::interface;
use rustc_middle::mir::interpret::GlobalId;
use rustc_middle::queries;
use rustc_middle::query::resident::ResidentQueryKey;
use rustc_middle::ty::{PseudoCanonicalInput, TyCtxt};

type TypeProvider =
    for<'tcx> fn(TyCtxt<'tcx>, LocalDefId) -> queries::typeck_root::ProvidedValue<'tcx>;
type BorrowProvider =
    for<'tcx> fn(TyCtxt<'tcx>, LocalDefId) -> queries::mir_borrowck::ProvidedValue<'tcx>;
type EvalProvider = for<'tcx> fn(
    TyCtxt<'tcx>,
    PseudoCanonicalInput<'tcx, GlobalId<'tcx>>,
) -> queries::eval_to_const_value_raw::ProvidedValue<'tcx>;
type AllocProvider = for<'tcx> fn(
    TyCtxt<'tcx>,
    PseudoCanonicalInput<'tcx, GlobalId<'tcx>>,
) -> queries::eval_to_allocation_raw::ProvidedValue<'tcx>;
static TYPE: OnceLock<TypeProvider> = OnceLock::new();
static BORROW: OnceLock<BorrowProvider> = OnceLock::new();
static EVAL: OnceLock<EvalProvider> = OnceLock::new();
static ALLOC: OnceLock<AllocProvider> = OnceLock::new();
static COUNTS: Mutex<BTreeMap<u32, [usize; 4]>> = Mutex::new(BTreeMap::new());

fn count(id: LocalDefId, index: usize) {
    COUNTS
        .lock()
        .unwrap()
        .entry(id.local_def_index.as_u32())
        .or_default()[index] += 1;
}
fn counts(id: LocalDefId) -> [usize; 4] {
    COUNTS
        .lock()
        .unwrap()
        .get(&id.local_def_index.as_u32())
        .copied()
        .unwrap_or_default()
}
fn counted_type<'tcx>(
    tcx: TyCtxt<'tcx>,
    id: LocalDefId,
) -> queries::typeck_root::ProvidedValue<'tcx> {
    count(id, 0);
    TYPE.get().unwrap()(tcx, id)
}
fn counted_borrow<'tcx>(
    tcx: TyCtxt<'tcx>,
    id: LocalDefId,
) -> queries::mir_borrowck::ProvidedValue<'tcx> {
    count(id, 1);
    BORROW.get().unwrap()(tcx, id)
}
fn counted_eval<'tcx>(
    tcx: TyCtxt<'tcx>,
    key: PseudoCanonicalInput<'tcx, GlobalId<'tcx>>,
) -> queries::eval_to_const_value_raw::ProvidedValue<'tcx> {
    if let Some(id) = key.value.instance.def_id().as_local() {
        count(id, 2);
    }
    EVAL.get().unwrap()(tcx, key)
}
fn counted_alloc<'tcx>(
    tcx: TyCtxt<'tcx>,
    key: PseudoCanonicalInput<'tcx, GlobalId<'tcx>>,
) -> queries::eval_to_allocation_raw::ProvidedValue<'tcx> {
    if let Some(id) = key.value.instance.def_id().as_local() {
        count(id, 3);
    }
    ALLOC.get().unwrap()(tcx, key)
}

struct Threshold<'tcx> {
    tcx: TyCtxt<'tcx>,
    found: Vec<HirId>,
}
impl<'tcx> Visitor<'tcx> for Threshold<'tcx> {
    fn visit_expr(&mut self, expr: &'tcx Expr<'tcx>) {
        if let ExprKind::Lit(lit) = expr.kind {
            let location = self.tcx.sess.source_map().lookup_char_pos(lit.span.lo());
            if matches!(lit.node, LitKind::Int(_, LitIntType::Unsuffixed))
                && location.line == 2511
                && location
                    .file
                    .get_line(location.line - 1)
                    .is_some_and(|line| line.contains("strings.len() <= 20"))
                && self
                    .tcx
                    .sess
                    .source_map()
                    .span_to_snippet(lit.span)
                    .is_ok_and(|source| source == "20")
            {
                self.found.push(expr.hir_id);
            }
        }
        intravisit::walk_expr(self, expr);
    }
}

fn check_function(
    tcx: TyCtxt<'_>,
    id: LocalDefId,
    name: &str,
    revision: &str,
) -> (bool, usize, [usize; 4]) {
    let result = tcx.typeck(id);
    let success = result.tainted_by_errors.is_none() && tcx.mir_borrowck(id).is_ok();
    let pointer = result as *const _ as usize;
    let count = counts(id);
    println!(
        "function\t{revision}\t{name}\t{success}\t{}\t{}\t{pointer}",
        count[0], count[1]
    );
    (success, pointer, count)
}

fn check_const(tcx: TyCtxt<'_>, id: LocalDefId, name: &str, revision: &str) -> bool {
    let result = tcx.const_eval_poly(id.to_def_id());
    let count = counts(id);
    println!(
        "constant\t{revision}\t{name}\t{}\t{}\t{}",
        result.is_ok(),
        count[2],
        count[3]
    );
    result.is_ok()
}

struct Driver;
impl Callbacks for Driver {
    fn config(&mut self, config: &mut interface::Config) {
        config.opts.trimmed_def_paths = true;
        config.override_queries = Some(|_, providers| {
            TYPE.set(providers.queries.typeck_root).unwrap();
            BORROW.set(providers.queries.mir_borrowck).unwrap();
            EVAL.set(providers.queries.eval_to_const_value_raw).unwrap();
            ALLOC.set(providers.queries.eval_to_allocation_raw).unwrap();
            providers.queries.typeck_root = counted_type;
            providers.queries.mir_borrowck = counted_borrow;
            providers.queries.eval_to_const_value_raw = counted_eval;
            providers.queries.eval_to_allocation_raw = counted_alloc;
        });
    }
    fn after_expansion<'tcx>(&mut self, _: &interface::Compiler, tcx: TyCtxt<'tcx>) -> Compilation {
        let graph = tcx
            .query_system
            .resident
            .as_ref()
            .expect("-Zohm-resident-query-graph");
        let mut selected = None;
        let mut functions = BTreeMap::new();
        let mut constants = BTreeMap::new();
        for id in tcx.hir_body_owners() {
            let kind = tcx.def_kind(id);
            let path =
                rustc_middle::ty::print::with_no_trimmed_paths!(tcx.def_path_str(id.to_def_id()));
            if matches!(kind, DefKind::Fn | DefKind::AssocFn) {
                let name = tcx.item_name(id.to_def_id()).to_string();
                let location = tcx.sess.source_map().lookup_char_pos(tcx.def_span(id).lo());
                if name == "new"
                    && location.line == 2509
                    && location
                        .file
                        .get_line(location.line - 1)
                        .is_some_and(|line| line.contains("const fn new(strings:"))
                {
                    assert!(selected.replace(id).is_none());
                }
                if [
                    "parse_pre",
                    "parse_post",
                    "sortable_tuple",
                    "starts_with_ignore_ascii_case",
                    "parse_u64",
                ]
                .contains(&name.as_str())
                    && path.starts_with("version::")
                {
                    assert!(functions.insert(name, id).is_none());
                }
            } else if matches!(kind, DefKind::Const { .. })
                && tcx.item_name(id.to_def_id()).as_str() == "SPELLINGS"
            {
                for name in ["parse_pre", "parse_post"] {
                    if path.contains(&format!("::{name}::SPELLINGS")) {
                        assert!(constants.insert(name, id).is_none());
                    }
                }
            }
        }
        let selected = selected.expect("production StringSet::new");
        assert_eq!(constants.len(), 2, "{constants:?}");
        assert_eq!(functions.len(), 5, "{functions:?}");
        let mut threshold = Threshold {
            tcx,
            found: Vec::new(),
        };
        threshold.visit_body(tcx.hir_body_owned_by(selected));
        assert_eq!(
            threshold.found.len(),
            1,
            "direct production threshold literal"
        );
        let threshold = threshold.found[0];
        println!("context\t{}\t{:p}", std::process::id(), *tcx);
        println!(
            "selected\t{}\t{threshold:?}",
            rustc_middle::ty::print::with_no_trimmed_paths!(tcx.def_path_str(selected.to_def_id()))
        );
        for (name, id) in &constants {
            println!(
                "owner\t{name}\t{}",
                rustc_middle::ty::print::with_no_trimmed_paths!(tcx.def_path_str(id.to_def_id()))
            );
        }
        tcx.ensure_ok().analysis(());
        assert_eq!(tcx.dcx().err_count(), 0, "whole production crate baseline");
        for (name, id) in &constants {
            assert!(check_const(tcx, *id, name, "initial"));
        }
        let initial = functions
            .iter()
            .map(|(name, id)| {
                let value = check_function(tcx, *id, name, "initial");
                assert!(value.0);
                (name.clone(), value)
            })
            .collect::<BTreeMap<_, _>>();
        assert!(check_function(tcx, selected, "selected", "initial").0);
        for (index, number) in [0u128, 20, 0, 20].into_iter().enumerate() {
            let revision = format!("{index}:{number}");
            eprintln!("uv-start:{revision}");
            tcx.dcx().reset_err_count();
            let affected = graph.affected([ResidentQueryKey::HirBody(selected)]);
            let result = unsafe {
                tcx.ohm_replace_private_body_integer_literal_with_invalidation(
                    selected,
                    threshold,
                    LitKind::Int(number.into(), LitIntType::Unsuffixed),
                )
            }
            .expect("supported integer edit in production associated const function")
            .expect("resident graph typed eviction");
            let mut removed = BTreeMap::new();
            for key in &result.removed {
                *removed.entry(key.query_name()).or_insert(0usize) += 1;
            }
            println!(
                "plan\t{revision}\t{}\t{}\t{}\t{}\t{}",
                result.revision,
                affected.len(),
                result.removed.len(),
                result.uncached.len(),
                result.trait_solver_caches_reset
            );
            for (name, count) in removed {
                println!("removed\t{revision}\t{name}\t{count}");
            }
            for (name, id) in &constants {
                check_const(tcx, *id, name, &revision);
            }
            check_function(tcx, selected, "selected", &revision);
            for (name, id) in &functions {
                if ["parse_pre", "parse_post"].contains(&name.as_str())
                    && std::env::var_os("OHM_UV_CHECK_PARSER_BORROW").is_none()
                {
                    continue;
                }
                let checked = check_function(tcx, *id, name, &revision);
                if [
                    "sortable_tuple",
                    "starts_with_ignore_ascii_case",
                    "parse_u64",
                ]
                .contains(&name.as_str())
                {
                    println!("cache\t{revision}\t{name}\t{}", checked == initial[name]);
                }
            }
            println!("errors\t{revision}\t{}", tcx.dcx().err_count());
            eprintln!("uv-end:{revision}");
        }
        tcx.dcx().reset_err_count();
        Compilation::Stop
    }
}

fn main() -> std::process::ExitCode {
    let args = std::env::args().collect::<Vec<_>>();
    rustc_driver::catch_with_exit_code(|| rustc_driver::run_compiler(&args, &mut Driver))
}
