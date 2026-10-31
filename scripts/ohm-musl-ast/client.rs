use ruff_python_ast::visitor::{self, Visitor};
use ruff_python_ast::{ElifElseClause, Expr, ExprNoneLiteral, Stmt, StmtIf};

#[derive(Default)]
struct Predicates(usize);

impl<'a> Visitor<'a> for Predicates {
    fn visit_expr(&mut self, expr: &'a Expr) {
        if matches!(expr, Expr::NoneLiteral(_)) {
            self.0 += 1;
        }
    }
}

#[derive(Default)]
struct Clauses(usize);

impl<'a> Visitor<'a> for Clauses {
    fn visit_elif_else_clause(&mut self, clause: &'a ElifElseClause) {
        self.0 += 1;
        visitor::walk_elif_else_clause(self, clause);
    }
}

fn main() {
    let test = Expr::NoneLiteral(ExprNoneLiteral::default());
    let clause = |test| ElifElseClause {
        range: Default::default(),
        node_index: Default::default(),
        test,
        body: Default::default(),
    };
    let stmt = Stmt::If(StmtIf {
        node_index: Default::default(),
        range: Default::default(),
        test: Box::new(Expr::EllipsisLiteral(Default::default())),
        body: Default::default(),
        elif_else_clauses: vec![clause(Some(test)), clause(None)],
    });
    let mut predicates = Predicates::default();
    let mut clauses = Clauses::default();
    predicates.visit_stmt(&stmt);
    clauses.visit_stmt(&stmt);
    println!("elif predicates {}, elif/else clauses {}", predicates.0, clauses.0);
}
