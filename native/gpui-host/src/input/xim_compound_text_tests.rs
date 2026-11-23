//! Regression for the XIM compound-text ASCII designation (ESC ( B).
#![cfg(target_os = "linux")]

#[test]
fn japanese_text_returns_to_ascii_without_leaking_the_designator() {
    let input = b"\x1b$(BCN$C$F$k$D$b$j\x1b(B end";
    assert_eq!(
        xim_ctext::compound_text_to_utf8(input).unwrap(),
        "知ってるつもり end"
    );
}
