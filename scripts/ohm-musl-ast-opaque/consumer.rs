mod lifetime_oracle {
    use ruff_python_ast::{
        ConversionFlag, Expr, InterpolatedElement, InterpolatedStringElement,
        InterpolatedStringElements, InterpolatedStringLiteralElement, StringLiteral,
        StringLiteralValue,
    };

    fn chars(x: &StringLiteralValue) -> impl Iterator<Item = char> + Clone + '_ {
        x.chars()
    }
    fn literals(
        x: &InterpolatedStringElements,
    ) -> impl Iterator<Item = &InterpolatedStringLiteralElement> {
        x.literals()
    }
    fn interpolations(
        x: &InterpolatedStringElements,
    ) -> impl Iterator<Item = &InterpolatedElement> {
        x.interpolations()
    }
    pub fn run() {
        let literal = |value: &str| StringLiteral {
            value: value.into(),
            range: Default::default(),
            node_index: Default::default(),
            flags: ruff_python_ast::StringLiteralFlags::empty(),
        };
        let string = StringLiteralValue::concatenated(vec![literal("λ"), literal("🦀")]);
        let left = InterpolatedStringLiteralElement {
            value: "left".into(),
            range: Default::default(),
            node_index: Default::default(),
        };
        let right = InterpolatedStringLiteralElement {
            value: "right".into(),
            range: Default::default(),
            node_index: Default::default(),
        };
        let expr = InterpolatedElement {
            range: Default::default(),
            node_index: Default::default(),
            expression: Box::new(Expr::NoneLiteral(Default::default())),
            debug_text: None,
            conversion: ConversionFlag::None,
            format_spec: None,
        };
        let pieces: InterpolatedStringElements = vec![
            InterpolatedStringElement::Literal(left),
            InterpolatedStringElement::Interpolation(expr),
            InterpolatedStringElement::Literal(right),
        ]
        .into();
        let iter = chars(&string);
        let lengths = iter.clone().count();
        let text: String = iter.collect();
        let fragments: Vec<&str> = literals(&pieces).map(|v| v.value.as_ref()).collect();
        let expressions = interpolations(&pieces)
            .filter(|v| matches!(v.expression.as_ref(), Expr::NoneLiteral(_)))
            .count();
        assert_eq!(
            (lengths, text.as_str(), fragments.as_slice(), expressions),
            (2, "λ🦀", ["left", "right"].as_slice(), 1)
        );
        println!(
            "chars {text}; literals {}; interpolations {expressions}",
            fragments.join(",")
        );
    }
}

mod additional_iterator_oracle {
    use ruff_python_ast::*;

    fn outer_literals(x: &FStringValue) -> impl Iterator<Item = &StringLiteral> {
        x.literals()
    }
    fn fstrings(x: &FStringValue) -> impl Iterator<Item = &FString> {
        x.f_strings()
    }
    fn fstring_elements(x: &FStringValue) -> impl Iterator<Item = &InterpolatedStringElement> {
        x.elements()
    }
    fn comparisons(
        x: &ExprCompare,
    ) -> impl DoubleEndedIterator<Item = (&Expr, &CmpOp, &Expr)> + ExactSizeIterator {
        x.iter()
    }
    fn params(x: &Parameters) -> impl Iterator<Item = &ParameterWithDefault> {
        x.iter_non_variadic_params()
    }
    fn bytes(x: &BytesLiteralValue) -> impl Iterator<Item = u8> + '_ {
        x.bytes()
    }
    fn template(x: &TStringValue) -> impl Iterator<Item = &InterpolatedStringElement> {
        x.elements()
    }

    fn text(s: &str) -> InterpolatedStringElement {
        InterpolatedStringElement::Literal(InterpolatedStringLiteralElement {
            value: s.into(),
            range: Default::default(),
            node_index: Default::default(),
        })
    }
    fn interpolation() -> InterpolatedStringElement {
        InterpolatedStringElement::Interpolation(InterpolatedElement {
            range: Default::default(),
            node_index: Default::default(),
            expression: Box::new(Expr::NoneLiteral(Default::default())),
            debug_text: None,
            conversion: ConversionFlag::None,
            format_spec: None,
        })
    }
    fn element_value(v: &InterpolatedStringElement) -> &str {
        match v {
            InterpolatedStringElement::Literal(v) => v.value.as_ref(),
            InterpolatedStringElement::Interpolation(v)
                if matches!(v.expression.as_ref(), Expr::NoneLiteral(_)) =>
            {
                "{}"
            }
            _ => panic!("unexpected interpolated expression"),
        }
    }
    fn fstring(elements: Vec<InterpolatedStringElement>) -> FString {
        FString {
            flags: FStringFlags::empty(),
            elements: elements.into(),
            range: Default::default(),
            node_index: Default::default(),
        }
    }
    fn string(value: &str) -> StringLiteral {
        StringLiteral {
            flags: StringLiteralFlags::empty(),
            value: value.into(),
            range: Default::default(),
            node_index: Default::default(),
        }
    }
    fn tstring(elements: Vec<InterpolatedStringElement>) -> TString {
        TString {
            flags: TStringFlags::empty(),
            elements: elements.into(),
            range: Default::default(),
            node_index: Default::default(),
        }
    }
    fn param(name: &str) -> Parameter {
        Parameter {
            name: Identifier::new(name, Default::default()),
            annotation: None,
            node_index: Default::default(),
            range: Default::default(),
        }
    }
    fn default_param(name: &str) -> ParameterWithDefault {
        ParameterWithDefault {
            parameter: param(name),
            default: None,
            node_index: Default::default(),
            range: Default::default(),
        }
    }
    fn byte_string(values: &[u8]) -> BytesLiteral {
        BytesLiteral {
            flags: BytesLiteralFlags::empty(),
            value: values.into(),
            range: Default::default(),
            node_index: Default::default(),
        }
    }
    pub fn run() {
        let lit = FStringValue::concatenated(vec![
            FStringPart::Literal(string("outside-a")),
            FStringPart::FString(fstring(vec![text("left"), interpolation(), text("right")])),
            FStringPart::Literal(string("outside-b")),
            FStringPart::FString(fstring(vec![text("tail")])),
        ]);
        let outside: Vec<&str> = outer_literals(&lit).map(|p| p.value.as_ref()).collect();
        let fs: Vec<_> = fstrings(&lit).collect();
        let widths: Vec<_> = fs.iter().map(|f| f.elements.len()).collect();
        let flat: Vec<_> = fstring_elements(&lit).collect();
        assert_eq!(outside, ["outside-a", "outside-b"]);
        assert_eq!(widths, [3, 1]);
        assert!(
            std::ptr::eq(flat[0], &fs[0].elements[0]) && std::ptr::eq(flat[3], &fs[1].elements[0])
        );
        let values: Vec<_> = flat.into_iter().map(element_value).collect();
        assert_eq!(values, ["left", "{}", "right", "tail"]);
        println!(
            "f-string outer {}; widths {},{}; body {}",
            outside.join(","),
            widths[0],
            widths[1],
            values.join(",")
        );

        let cmp = ExprCompare {
            ops: vec![CmpOp::Lt, CmpOp::IsNot].into_boxed_slice(),
            operands: vec![
                Expr::NoneLiteral(Default::default()),
                Expr::EllipsisLiteral(Default::default()),
                Expr::NoneLiteral(Default::default()),
            ]
            .into_boxed_slice(),
            node_index: Default::default(),
            range: Default::default(),
        };
        let mut iter = comparisons(&cmp);
        let before = iter.len();
        let (middle, last_op, last) = iter.next_back().unwrap();
        let remaining = iter.len();
        let (first, first_op, again) = iter.next().unwrap();
        let empty = iter.len();
        assert!(
            std::ptr::eq(first, &cmp.operands[0])
                && std::ptr::eq(middle, &cmp.operands[1])
                && std::ptr::eq(middle, again)
                && std::ptr::eq(last, &cmp.operands[2])
                && std::ptr::eq(first_op, &cmp.ops[0])
                && std::ptr::eq(last_op, &cmp.ops[1])
        );
        assert_eq!((before, remaining, empty), (2, 1, 0));
        assert!(
            iter.next_back().is_none()
                && matches!(first_op, CmpOp::Lt)
                && matches!(last_op, CmpOp::IsNot)
        );
        println!("comparison <,is not; lengths {before},{remaining},{empty}");

        let parameters = Parameters {
            posonlyargs: [default_param("head")].into_iter().collect(),
            args: [default_param("normal")].into_iter().collect(),
            kwonlyargs: [default_param("key")].into_iter().collect(),
            vararg: Some(Box::new(param("args"))),
            kwarg: Some(Box::new(param("kwargs"))),
            range: Default::default(),
            node_index: Default::default(),
        };
        let actual: Vec<_> = params(&parameters).collect();
        assert!(
            std::ptr::eq(actual[0], &parameters.posonlyargs[0])
                && std::ptr::eq(actual[1], &parameters.args[0])
                && std::ptr::eq(actual[2], &parameters.kwonlyargs[0])
        );
        let names: Vec<_> = actual
            .into_iter()
            .map(|p| p.parameter.name.as_str())
            .collect();
        assert_eq!(names, ["head", "normal", "key"]);
        let b = BytesLiteralValue::concatenated(vec![byte_string(&[0, 255]), byte_string(&[65])]);
        let raw: Vec<_> = bytes(&b).collect();
        assert_eq!(raw, [0, 255, 65]);
        let ts = TStringValue::concatenated(vec![
            tstring(vec![text("tee"), interpolation()]),
            tstring(vec![text("last")]),
        ]);
        let flat: Vec<_> = template(&ts).collect();
        assert!(
            std::ptr::eq(flat[0], &ts.as_slice()[0].elements[0])
                && std::ptr::eq(flat[2], &ts.as_slice()[1].elements[0])
        );
        let values: Vec<_> = flat.into_iter().map(element_value).collect();
        assert_eq!(values, ["tee", "{}", "last"]);
        println!(
            "nonvariadic {}; bytes {:02x},{:02x},{:02x}; template {}",
            names.join(","),
            raw[0],
            raw[1],
            raw[2],
            values.join(",")
        );
    }
}

fn main() {
    visitor();
    lifetime_oracle::run();
    additional_iterator_oracle::run();
}
