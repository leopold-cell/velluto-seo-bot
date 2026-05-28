"""
Phase 4.7 smoke test — markdown-fence stripping + gate FENCE check.
No network. Run: python3 tests/smoke_test_phase4_7.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=" * 60)
print("=== Phase 4.7 Smoke Test ===")
print("=" * 60)

# ── 1. _strip_md_fence ───────────────────────────────────────
print("\n🧹 Step 1: _strip_md_fence()")
from seo_bot import _strip_md_fence

cases = [
    ("```html\n<p>Sie sind 4 km vom Gipfel</p>\n```", "<p>Sie sind 4 km vom Gipfel</p>"),
    ("```\n<h1>Title</h1>\n```",                        "<h1>Title</h1>"),
    ("<p>no fence here</p>",                            "<p>no fence here</p>"),
    ("```HTML\n<p>upper lang tag</p>\n```",             "<p>upper lang tag</p>"),
    ("  ```html\n<p>leading spaces</p>\n```  ",         "<p>leading spaces</p>"),
]
for inp, expected in cases:
    out = _strip_md_fence(inp)
    assert out == expected, f"❌ {inp!r} → {out!r} (expected {expected!r})"
    print(f"   ✓ {inp[:35]!r:38} → {out[:40]!r}")
# Idempotent + handles internal ``` only at edges
assert "```" not in _strip_md_fence("```html\n<p>x</p>\n```")
print("   ✓ no fence remains after strip")

# ── 2. quality_gate FENCE check ──────────────────────────────
print("\n🚦 Step 2: quality_gate.check_no_markdown_fence()")
from briefs.quality_gate import check_no_markdown_fence

fenced = {"body_html": "```html\n<p>x</p>\n```"}
clean  = {"body_html": "<p>clean body, " + "word " * 200 + "</p>"}
assert check_no_markdown_fence(fenced), "❌ should flag fenced body"
assert not check_no_markdown_fence(clean), "❌ should NOT flag clean body"
print(f"   ✓ fenced body flagged: {check_no_markdown_fence(fenced)[0]}")
print(f"   ✓ clean body not flagged")

# ── 3. CSS contains table rules ──────────────────────────────
print("\n🎨 Step 3: theme CSS has responsive table rules")
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
css = open(os.path.join(root, "theme/assets/velluto-magazine.css")).read()
assert ".vmag .vmag-content table" in css, "❌ table base rule missing"
assert "overflow-x:auto" in css, "❌ mobile scroll rule missing"
assert "min-width:110px" in css, "❌ mobile cell min-width missing"
print("   ✓ table base + mobile overflow-x:auto + cell min-width present")

print("\n" + "=" * 60)
print("🎉 Phase 4.7 smoke test PASSED")
print("=" * 60)
