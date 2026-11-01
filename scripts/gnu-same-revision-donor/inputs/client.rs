use ruff_python_ast::{self as ast, Expr, ExprCall, ExprContext, ExprName, Arguments, name::Name, token::Tokens};
use ruff_text_size::{TextRange,TextSize};
fn range(a:u32,b:u32)->TextRange {TextRange::new(a.into(),b.into())}
fn name(label:&str,start:u32,end:u32)->Expr { Expr::Name(ExprName { node_index: Default::default(), range: range(start,end), id:Name::new(label),ctx:ExprContext::Load }) }
fn main() {
  let expr=name("x",5,6);
  let call=ExprCall {node_index:Default::default(),range_start:TextSize::from(0),func:Box::new(name("wrap",0,4)),arguments:Arguments {node_index:Default::default(),range:range(4,7),args:vec![expr.clone()].into_iter().collect(),keywords:Default::default()}};
  let actual=ruff_python_edits::unwrapped_call_argument(&call,&expr,None,&Tokens::new(vec![]),"wrap(x)");
  let arg = std::env::args().nth(1).expect("extension argument");
  let ty = ast::PySourceType::try_from_extension(&arg).expect("known extension");
  println!("{} {} {:?}", std::mem::size_of::<ast::Expr>(), actual, ty);
}
