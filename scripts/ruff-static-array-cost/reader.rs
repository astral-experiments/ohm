fn main() {
    for s in ["latinsmalllettera", "Black_Star", "latin SMALL letter A", "BLACK STAR", "SNOWMAN", "NO SUCH CODE POINT"] {
        println!("{s}={:?}", unicode_names2::character(s).map(u32::from));
    }
}
