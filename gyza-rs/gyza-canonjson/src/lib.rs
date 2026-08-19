//! Canonical JSON bytes, byte-identical to Python's
//! `json.dumps(obj, sort_keys=True, separators=(",", ":"))`.
//!
//! # Why this crate exists
//!
//! Every signature in Gyza covers `BLAKE3(canonical_bytes)`. If Python and
//! Rust disagree about those bytes by even one character, a signature
//! produced by one **does not verify on the other**, and the failure reads
//! as tampering rather than as an encoding bug.
//!
//! They did disagree. `serde_json` emits raw UTF-8; Python's `json.dumps`
//! defaults to `ensure_ascii=True` and escapes. Measured on 2026-08-06
//! (`research/respecification/FINDINGS_SURVEY.md`):
//!
//! ```text
//! input "caf\u{e9}"    python: "caf\u00e9"          rust WAS: "caf<c3><a9>"
//! input "x\u{1F510}y"  python: "x\ud83d\udd10y"    rust WAS: "x<f0><9f><94><90>y"
//! ```
//!
//! **The fix belongs on this side.** Making Python stop escaping would
//! change the canonical bytes of every envelope ever signed and invalidate
//! the entire stored history. Rust must be made to escape.
//!
//! # The rule, DERIVED BY SWEEP rather than from the spec
//!
//! A sweep of `json.dumps(chr(cp))` over `cp` in `0x00..=0x11F` shows Python
//! escapes exactly:
//!
//! ```text
//! c < 0x20  ||  c == 0x22 (")  ||  c == 0x5c (\)  ||  c >= 0x7f
//! ```
//!
//! `serde_json` already matches the first three. **The delta is `c >= 0x7f`,
//! and that lower bound is 0x7f, not 0x80**: Python escapes DEL (U+007F),
//! which is ASCII. Implementing "escape non-ASCII" from the specification
//! would have missed it — which is why the rule was measured.
//!
//! Escapes are lowercase hex, and astral codepoints become **UTF-16
//! surrogate pairs**, matching Python.
//!
//! # Why one crate rather than a copy in each caller
//!
//! `gyza-icp` and `gyza-capability` both need this and neither depends on the
//! other. Copying the escaper into both would reproduce, exactly, the defect
//! this crate was created to fix: two implementations of one logical
//! operation, free to drift. There is one implementation. It lives here.

//! # Non-finite floats: a LIMITATION, not a guard
//!
//! Python's canonical encoders pass `allow_nan=False` and RAISE on NaN or
//! Infinity. **This crate cannot do the same at the formatter layer, and the
//! asymmetry is recorded here rather than papered over with a check that
//! cannot fire.**
//!
//! `serde_json`'s `serialize_f64` classifies the value ITSELF and routes
//! non-finite to `Formatter::write_null`, so an overridden `write_f64` is
//! never reached. `write_null` cannot be overridden to reject, because a
//! legitimate `Option::None` uses the same path -- `EnvelopePayload
//! ::parent_envelope_hash` is exactly that.
//!
//! **The consequence is NOT a signature mismatch.** Rust emits `null`; Python
//! parsing that JSON gets `None` and re-canonicalizes to `null`, so the two
//! sides agree byte-for-byte and verification still succeeds. What is lost is
//! the DISTINCTION between "absent" and "was NaN" -- silent degradation on the
//! Rust side against a hard refusal on the Python side.
//!
//! This is reachable: `ChallengeResponsePayload` carries `eval_results` whose
//! `EvalResult` has `duration_s: f64`, on a signed path. Closing it properly
//! needs a wrapping `Serializer` that intercepts `serialize_f64` before
//! `serde_json` classifies -- roughly the whole `Serializer` trait in
//! boilerplate -- and is deliberately NOT done here. The behaviour is pinned
//! by `non_finite_floats_currently_become_null` so it is visible and any
//! change is caught.

use serde::Serialize;
use serde_json::ser::Formatter;
use std::io;

/// Escapes every codepoint `>= 0x7f` as `\uXXXX`, using surrogate pairs
/// above the BMP, so output matches Python's `ensure_ascii=True`.
///
/// Only `write_string_fragment` is overridden. `serde_json` calls it with
/// the runs of characters its own escape table considered safe, and hands
/// control characters, `"` and `\` to `write_char_escape` — where its
/// behaviour already matches Python. Everything else (compact separators,
/// no whitespace) is inherited from the default compact formatter, so key
/// order and structure are untouched.
#[derive(Clone, Copy, Debug, Default)]
pub struct EnsureAsciiFormatter;

impl Formatter for EnsureAsciiFormatter {
    fn write_string_fragment<W>(&mut self, writer: &mut W, fragment: &str) -> io::Result<()>
    where
        W: ?Sized + io::Write,
    {
        let mut pending = 0usize; // start of the current pass-through run
        for (idx, ch) in fragment.char_indices() {
            let cp = ch as u32;
            if cp < 0x7f {
                continue; // accumulate; flushed in one write below
            }
            if pending < idx {
                writer.write_all(&fragment.as_bytes()[pending..idx])?;
            }
            write_u_escape(writer, cp)?;
            pending = idx + ch.len_utf8();
        }
        if pending < fragment.len() {
            writer.write_all(&fragment.as_bytes()[pending..])?;
        }
        Ok(())
    }
}

fn write_u_escape<W>(writer: &mut W, cp: u32) -> io::Result<()>
where
    W: ?Sized + io::Write,
{
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let emit = |unit: u32, w: &mut W| -> io::Result<()> {
        let b = [
            b'\\',
            b'u',
            HEX[((unit >> 12) & 0xf) as usize],
            HEX[((unit >> 8) & 0xf) as usize],
            HEX[((unit >> 4) & 0xf) as usize],
            HEX[(unit & 0xf) as usize],
        ];
        w.write_all(&b)
    };
    if cp > 0xFFFF {
        // UTF-16 surrogate pair, exactly as Python emits for astral chars.
        let v = cp - 0x1_0000;
        emit(0xD800 + (v >> 10), writer)?;
        emit(0xDC00 + (v & 0x3FF), writer)
    } else {
        emit(cp, writer)
    }
}

/// Serialize to canonical JSON bytes matching Python's
/// `json.dumps(sort_keys=True, separators=(",", ":"))`.
///
/// Key ORDER is the caller's responsibility: Rust structs must declare
/// fields in alphabetical order to match Python's `sort_keys=True`. This
/// function fixes the ENCODING, not the ordering.
pub fn to_vec<T: Serialize + ?Sized>(value: &T) -> Result<Vec<u8>, serde_json::Error> {
    let mut buf = Vec::with_capacity(128);
    let mut ser = serde_json::Serializer::with_formatter(&mut buf, EnsureAsciiFormatter);
    value.serialize(&mut ser)?;
    Ok(buf)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Fixtures are the MEASURED output of Python's `json.dumps`, pasted
    /// from a real run — never hand-written from the spec. Regenerate with
    /// `gyza-rs/scripts/regenerate_canonjson_fixtures.py`.
    /// Serialize anything and return the canonical string. `py` above is
    /// kept &str-only so the existing fixtures read unchanged.
    fn canon<T: Serialize + ?Sized>(v: &T) -> String {
        String::from_utf8(to_vec(v).expect("serialize")).expect("utf8")
    }

    fn py(s: &str) -> String {
        String::from_utf8(to_vec(s).expect("serialize")).expect("utf8")
    }

    /// GENERATED fixtures -- Python's REAL `json.dumps` output, pasted from
    /// `gyza-rs/scripts/regenerate_canonjson_fixtures.py`. The first version of
    /// these was hand-written from the spec and failed against a CORRECT
    /// implementation, because literal `\u{e9}` and literal control characters
    /// had been typed into the source instead of the escape TEXT.
    #[test]
    fn matches_python_byte_for_byte() {
        // ascii
        assert_eq!(py("abc"), r#""abc""#);
        // solidus
        assert_eq!(py("a/b"), r#""a/b""#);
        // quote
        assert_eq!(py("a\"b"), r#""a\"b""#);
        // backslash
        assert_eq!(py("a\\b"), r#""a\\b""#);
        // newline
        assert_eq!(py("a\u{a}b"), r#""a\nb""#);
        // tab
        assert_eq!(py("a\u{9}b"), r#""a\tb""#);
        // cr
        assert_eq!(py("a\u{d}b"), r#""a\rb""#);
        // backspace
        assert_eq!(py("a\u{8}b"), r#""a\bb""#);
        // formfeed
        assert_eq!(py("a\u{c}b"), r#""a\fb""#);
        // vtab_0x0b
        assert_eq!(py("a\u{b}b"), r#""a\u000bb""#);
        // null_0x00
        assert_eq!(py("a\u{0}b"), r#""a\u0000b""#);
        // us_0x1f
        assert_eq!(py("a\u{1f}b"), r#""a\u001fb""#);
        // tilde_0x7e
        assert_eq!(py("~"), r#""~""#);
        // del_0x7f
        assert_eq!(py("a\u{7f}b"), r#""a\u007fb""#);
        // latin1_e9
        assert_eq!(py("caf\u{e9}"), r#""caf\u00e9""#);
        // combining_nfd
        assert_eq!(py("cafe\u{301}"), r#""cafe\u0301""#);
        // cjk
        assert_eq!(py("\u{4e2d}\u{6587}"), r#""\u4e2d\u6587""#);
        // bmp_max
        assert_eq!(py("\u{ffff}"), r#""\uffff""#);
        // nbsp_a0
        assert_eq!(py("a\u{a0}b"), r#""a\u00a0b""#);
        // rtl_mark
        assert_eq!(py("a\u{200f}b"), r#""a\u200fb""#);
        // astral_emoji
        assert_eq!(py("x\u{1f510}y"), r#""x\ud83d\udd10y""#);
        // astral_max
        assert_eq!(py("\u{10ffff}"), r#""\udbff\udfff""#);
    }

    /// NFC and NFD render alike and are different byte sequences. Neither
    /// side normalizes, so both must escape them DIFFERENTLY and identically
    /// to Python -- a canonicalizer that silently normalized would make two
    /// distinct claims hash the same.
    #[test]
    fn nfc_and_nfd_stay_distinct() {
        let nfc = py("caf\u{e9}");
        let nfd = py("cafe\u{301}");
        assert_ne!(nfc, nfd);
        assert_eq!(nfc, r#""caf\u00e9""#);
        assert_eq!(nfd, r#""cafe\u0301""#);
    }

    /// Object KEYS go through the same formatter as values.
    #[test]
    fn non_ascii_object_keys_are_escaped_too() {
        use std::collections::BTreeMap;
        let mut m = BTreeMap::new();
        m.insert("caf\u{e9}", 1);
        let out = String::from_utf8(to_vec(&m).unwrap()).unwrap();
        assert_eq!(out, r#"{"caf\u00e9":1}"#);
    }

    /// Compact separators must survive the custom formatter.
    #[test]
    fn output_stays_compact() {
        use std::collections::BTreeMap;
        let mut m = BTreeMap::new();
        m.insert("b", vec![1, 2]);
        m.insert("a", vec![3]);
        let out = String::from_utf8(to_vec(&m).unwrap()).unwrap();
        assert_eq!(out, r#"{"a":[3],"b":[1,2]}"#);
        assert!(!out.contains(' '));
    }

    /// PINS A KNOWN LIMITATION (see the module header). Python RAISES on
    /// these; this crate emits `null` because serde_json classifies
    /// non-finite before the formatter is consulted.
    ///
    /// Not a signature divergence -- Python re-canonicalizing that `null`
    /// produces the same bytes -- but the "absent vs was-NaN" distinction is
    /// lost. If this test starts failing, the asymmetry has been closed and
    /// the module header must be updated.
    #[test]
    fn non_finite_floats_currently_become_null() {
        for bad in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
            assert_eq!(canon(&bad), "null", "serde_json nulls non-finite f64");
        }
        for bad in [f32::NAN, f32::INFINITY, f32::NEG_INFINITY] {
            assert_eq!(canon(&bad), "null", "serde_json nulls non-finite f32");
        }
    }

    /// Finite floats must still round-trip byte-identically to Python.
    #[test]
    fn finite_floats_still_match_python() {
        // MEASURED from python: json.dumps(v, separators=(",", ":"))
        assert_eq!(canon(&1.5f64), "1.5");
        assert_eq!(canon(&0.0f64), "0.0");
        assert_eq!(canon(&-2.25f64), "-2.25");
    }

    /// The reachable case: a struct with a float, as on the signed
    /// ChallengeResponsePayload path.
    #[test]
    fn a_struct_carrying_a_non_finite_float_becomes_null() {
        #[derive(serde::Serialize)]
        struct Evalish {
            duration_s: f64,
            task_id: &'static str,
        }
        let ok = Evalish {
            duration_s: 0.25,
            task_id: "t",
        };
        assert_eq!(canon(&ok), r#"{"duration_s":0.25,"task_id":"t"}"#);
        // The reachable case, pinned: NaN inside a signed struct becomes null
        // rather than raising as Python does.
        let bad = Evalish {
            duration_s: f64::NAN,
            task_id: "t",
        };
        assert_eq!(canon(&bad), r#"{"duration_s":null,"task_id":"t"}"#);
    }
}
