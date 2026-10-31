mod lifetime_oracle {
    use ruff_python_ast::{
        ConversionFlag, Expr, InterpolatedElement, InterpolatedStringElement,
        InterpolatedStringElements, InterpolatedStringLiteralElement, StringLiteral, StringLiteralValue,
    };

    fn chars(x: &StringLiteralValue) -> impl Iterator<Item = char> + Clone + '_ {
        x.chars()
    }
    fn literals(x: &InterpolatedStringElements) -> impl Iterator<Item = &InterpolatedStringLiteralElement> {
        x.literals()
    }
    fn interpolations(x: &InterpolatedStringElements) -> impl Iterator<Item = &InterpolatedElement> {
        x.interpolations()
    }
    pub fn run() {
        let literal = |value: &str| StringLiteral {
            value: value.into(), range: Default::default(), node_index: Default::default(), flags: ruff_python_ast::StringLiteralFlags::empty(),
        };
        let string = StringLiteralValue::concatenated(vec![literal("λ"), literal("🦀")]);
        let left = InterpolatedStringLiteralElement {
            value: "left".into(), range: Default::default(), node_index: Default::default(),
        };
        let right = InterpolatedStringLiteralElement {
            value: "right".into(), range: Default::default(), node_index: Default::default(),
        };
        let expr = InterpolatedElement {
            range: Default::default(), node_index: Default::default(), expression: Box::new(Expr::NoneLiteral(Default::default())),
            debug_text: None, conversion: ConversionFlag::None, format_spec: None,
        };
        let pieces: InterpolatedStringElements = vec![
            InterpolatedStringElement::Literal(left), InterpolatedStringElement::Interpolation(expr),
            InterpolatedStringElement::Literal(right)
        ].into();
        let iter = chars(&string);
        let lengths = iter.clone().count();
        let text: String = iter.collect();
        let fragments: Vec<&str> = literals(&pieces).map(|v| v.value.as_ref()).collect();
        let expressions = interpolations(&pieces).filter(|v| matches!(v.expression.as_ref(),Expr::NoneLiteral(_))).count();
        assert_eq!((lengths,text.as_str(),fragments.as_slice(),expressions),(2,"λ🦀",["left","right"].as_slice(),1));
        println!("chars {text}; literals {}; interpolations {expressions}", fragments.join(","));
    }
}
fn main() { visitor(); lifetime_oracle::run(); }
