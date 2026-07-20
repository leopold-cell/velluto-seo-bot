"""
Smoke test for the HTML segment tokenizer (briefs.html_segments).

The safety guarantee the market-adaptation refactor relies on:
    detokenize(parts, ORIGINAL_segments) == original_html   (exact roundtrip)
so any segment-count mismatch from the LLM is detectable and the caller falls back to
full-body adaptation. Also checks heading/alt roles and that markup/URLs never leak into
the translatable segments.

No network, no LLM. Run: python3 tests/smoke_test_html_segments.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from briefs.html_segments import tokenize, detokenize, first_body_index

fails = []
def ok(cond, label):
    print(("   ✓ " if cond else "   ✗ FAIL ") + label)
    if not cond:
        fails.append(label)


SAMPLE = (
    '<h1>Best Road Cycling Sunglasses</h1>\n'
    '<p>The <a href="https://velluto-shop.com/collections/x">Velluto StradaPro</a> '
    'weighs 25 g.</p>\n'
    '<figure><img src="https://cdn.example/x.jpg" alt="Velluto StradaPro in Nero"></figure>\n'
    '<h2 id="sfaq">FAQ</h2>\n'
    '<details><summary>Is it UV400?</summary><p>Yes, certified.</p></details>'
)

print("=== exact roundtrip (the safety guarantee) ===")
parts, segments, roles = tokenize(SAMPLE)
ok(detokenize(parts, segments) == SAMPLE, "detokenize(tokenize(h)) == h  (identity)")

# Simulate an LLM adaptation: replace each segment with a marked version, reinsert.
adapted = [f"«{s}»" for s in segments]
out = detokenize(parts, adapted)
ok(all(f"«{s}»" in out for s in segments), "adapted segments reinserted into skeleton")
ok(out.count('<a href="https://velluto-shop.com/collections/x">') == 1
   and 'src="https://cdn.example/x.jpg"' in out
   and 'id="sfaq"' in out,
   "URLs / classes / ids / tags survive adaptation untouched")

print("\n=== segments contain TEXT only, never markup ===")
ok(not any("<" in s or ">" in s for s in segments), "no tags leaked into segments")
ok(not any("http" in s for s in segments), "no URLs leaked into segments")
ok("Velluto StradaPro in Nero" in segments, "img alt text IS extracted (translatable)")
ok("Best Road Cycling Sunglasses" in segments, "heading text extracted")

print("\n=== roles (for keyword placement) ===")
ok(roles[segments.index("Best Road Cycling Sunglasses")] == "h1", "H1 text tagged 'h1'")
ok(roles[segments.index("FAQ")] == "h2", "H2 text tagged 'h2'")
ok(roles[segments.index("Velluto StradaPro in Nero")] == "attr", "alt text tagged 'attr'")
ok(segments[first_body_index(roles)] == "Best Road Cycling Sunglasses",
   "first_body_index points at the opening heading (SEO-critical)")

print("\n=== edge cases ===")
for h in ["", "plain text no tags", "<p></p>", "<br/>", "<p>   </p>",
          "<p>a</p><p>b</p>", "<img alt='' src='x'>", "<p>Nur Text &amp; Entität</p>"]:
    p, s, r = tokenize(h)
    ok(detokenize(p, s) == h, f"roundtrip exact: {h[:32]!r}")

print("\n" + ("✅ ALL PASSED" if not fails else f"❌ {len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
