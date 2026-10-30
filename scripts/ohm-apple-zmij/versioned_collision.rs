#![feature(proc_macro_tracked_path)]
extern crate proc_macro;
use proc_macro::TokenStream;
#[proc_macro]
pub fn observed(arg: TokenStream) -> TokenStream {
    match arg.to_string().as_str() {
        "none" => {},
        "v1" => proc_macro::tracked::path("/dev/null/ohm-recheck-dependent-links"),
        "v2" => proc_macro::tracked::path("/dev/null/ohm-recheck-dependent-links-v2"),
        "both" => { proc_macro::tracked::path("/dev/null/ohm-recheck-dependent-links"); proc_macro::tracked::path("/dev/null/ohm-recheck-dependent-links-v2"); },
        _ => panic!(),
    }
    "17usize".parse().unwrap()
}
