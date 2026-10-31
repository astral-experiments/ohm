#[test] fn root_value(){let value=fixture_dep::value();println!("actual native = {value}");assert_eq!(value,std::env::var("WANT").unwrap().parse::<u8>().unwrap());}
