#![feature(rustc_private)]

extern crate rustc_ast;
extern crate rustc_driver;
extern crate rustc_hir;
extern crate rustc_interface;
extern crate rustc_middle;
extern crate rustc_span;

use std::collections::BTreeMap;
use std::sync::{Mutex, OnceLock};

use rustc_ast::{LitIntType, LitKind};
use rustc_driver::{Callbacks, Compilation};
use rustc_hir::def::DefKind;
use rustc_hir::def_id::LocalDefId;
use rustc_hir::{ExprKind, PatKind};
use rustc_interface::interface;
use rustc_middle::hir::map::OhmResidentTailExpr;
use rustc_middle::queries;
use rustc_middle::query::resident::ResidentQueryKey;
use rustc_middle::ty::TyCtxt;
use rustc_span::BytePos;

type TypeProvider =
    for<'tcx> fn(TyCtxt<'tcx>, LocalDefId) -> queries::typeck_root::ProvidedValue<'tcx>;
type BorrowProvider =
    for<'tcx> fn(TyCtxt<'tcx>, LocalDefId) -> queries::mir_borrowck::ProvidedValue<'tcx>;
static TYPE: OnceLock<TypeProvider> = OnceLock::new();
static BORROW: OnceLock<BorrowProvider> = OnceLock::new();
static COUNTS: Mutex<BTreeMap<u32, [usize; 2]>> = Mutex::new(BTreeMap::new());

fn count(id: LocalDefId, index: usize) {
    COUNTS
        .lock()
        .unwrap()
        .entry(id.local_def_index.as_u32())
        .or_default()[index] += 1;
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

struct Driver;

impl Callbacks for Driver {
    fn config(&mut self, config: &mut interface::Config) {
        config.override_queries = Some(|_, providers| {
            TYPE.set(providers.queries.typeck_root).unwrap();
            BORROW.set(providers.queries.mir_borrowck).unwrap();
            providers.queries.typeck_root = counted_type;
            providers.queries.mir_borrowck = counted_borrow;
        });
    }

    fn after_expansion<'tcx>(&mut self, _: &interface::Compiler, tcx: TyCtxt<'tcx>) -> Compilation {
        assert!(
            tcx.query_system.resident.is_some(),
            "-Zohm-resident-query-graph"
        );
        let mut functions = tcx
            .hir_body_owners()
            .filter(|id| tcx.def_kind(*id) == DefKind::Fn)
            .map(|id| (tcx.item_name(id.to_def_id()).to_string(), id))
            .collect::<BTreeMap<_, _>>();
        let selected = functions.remove("selected").expect("selected");
        let untouched = *functions.get("untouched").expect("untouched");
        let baseline = check(tcx, selected, "selected", "initial");
        assert!(baseline.0);
        let initial_untouched = check(tcx, untouched, "untouched", "initial").1;
        for (name, &id) in &functions {
            assert!(check(tcx, id, name, "initial").0);
        }
        assert_eq!(tcx.dcx().err_count(), 0);
        println!("context\t{:p}", *tcx);

        let edits = std::env::var("OHM_TYPED_EDITS").expect("OHM_TYPED_EDITS");
        for (index, text) in edits.split(',').enumerate() {
            eprintln!("typed-start:{index}");
            tcx.dcx().reset_err_count();
            let body = tcx.hir_body_owned_by(selected);
            let ExprKind::Block(block, None) = body.value.kind else {
                panic!("expected selected block")
            };
            let tail = block.expr.expect("selected tail");
            let span = tail
                .span
                .with_hi(tail.span.lo() + BytePos(text.len().try_into().unwrap()));
            let replacement = if let Ok(number) = text.parse::<u128>() {
                OhmResidentTailExpr::Literal(
                    LitKind::Int(number.into(), LitIntType::Unsuffixed),
                    span,
                )
            } else if matches!(text, "true" | "false") {
                OhmResidentTailExpr::Literal(LitKind::Bool(text == "true"), span)
            } else {
                let binding = body
                    .params
                    .iter()
                    .find_map(|param| match param.pat.kind {
                        PatKind::Binding(_, binding, name, None) if name.as_str() == text => {
                            Some(binding)
                        }
                        _ => None,
                    })
                    .expect("named selected parameter");
                OhmResidentTailExpr::Local(binding, span)
            };
            let graph = tcx.query_system.resident.as_ref().unwrap();
            let affected = graph.affected([ResidentQueryKey::HirBody(selected)]);
            if index == 0 {
                let mut edges = Vec::new();
                for key in &affected {
                    for dependency in graph.dependencies(*key) {
                        if affected.contains(&dependency) {
                            edges.push(format!("{key:?}\t{dependency:?}"));
                        }
                    }
                }
                edges.sort_unstable();
                for edge in edges {
                    println!("edge\t{edge}");
                }
                let solver = graph.affected([ResidentQueryKey::TraitSolver]);
                let mut solver_edges = Vec::new();
                for key in &solver {
                    for dependency in graph.dependencies(*key) {
                        if solver.contains(&dependency) {
                            solver_edges.push(format!("{key:?}\t{dependency:?}"));
                        }
                    }
                }
                solver_edges.sort_unstable();
                for edge in solver_edges {
                    println!("solver-edge\t{edge}");
                }
            }
            let result = unsafe {
                tcx.ohm_replace_private_body_tail_with_invalidation(selected, replacement)
            }
            .expect("body edit was supported")
            .expect("tracked eviction");
            let mut removed = result
                .removed
                .iter()
                .map(|key| format!("{}:{:?}", key.query_name(), key))
                .collect::<Vec<_>>();
            removed.sort_unstable();
            println!(
                "plan\t{index}\t{text}\trev={}\taffected={}\tremoved={}\tmissing={}\tsolver={}",
                result.revision,
                affected.len(),
                result.removed.len(),
                result.uncached.len(),
                result.trait_solver_caches_reset
            );
            for key in removed {
                println!("removed\t{index}\t{key}");
            }
            check(tcx, selected, "selected", text);
            for (name, &id) in &functions {
                let result = check(tcx, id, name, text);
                if id == untouched {
                    assert!(result.0);
                    assert_eq!(initial_untouched, result.1);
                    assert_eq!(
                        COUNTS.lock().unwrap()[&untouched.local_def_index.as_u32()],
                        [1, 1]
                    );
                }
            }
            println!("errors\t{index}\t{text}\t{}", tcx.dcx().err_count());
            eprintln!("typed-end:{index}");
        }
        tcx.dcx().reset_err_count();
        Compilation::Stop
    }
}

fn check(tcx: TyCtxt<'_>, id: LocalDefId, name: &str, edit: &str) -> (bool, usize) {
    let result = tcx.typeck(id);
    let success = result.tainted_by_errors.is_none() && tcx.mir_borrowck(id).is_ok();
    let counts = COUNTS.lock().unwrap()[&id.local_def_index.as_u32()];
    let pointer = result as *const _ as usize;
    println!(
        "check\t{edit}\t{name}\t{success}\t{}\t{}\t{pointer}",
        counts[0], counts[1]
    );
    (success, pointer)
}

fn main() -> std::process::ExitCode {
    let args = std::env::args().collect::<Vec<_>>();
    rustc_driver::catch_with_exit_code(|| rustc_driver::run_compiler(&args, &mut Driver))
}
