"""
Offline smoke test for image_generator.py (no OpenAI/Shopify network).

Run: python3 tests/smoke_test_image_generator.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import image_generator as ig

failures = []


def check(name, cond):
    print(("✅" if cond else "❌") + f" {name}")
    if not cond:
        failures.append(name)


# ── prompt / alt / slug ─────────────────────────────────────────────────────
p = ig.build_prompt("anti-fog cycling glasses for cold climbs")
check("prompt mentions topic", "anti-fog cycling glasses" in p)
check("prompt forbids text/logos", "No text" in p and "no logos" in p)
check("prompt avoids forbidden features",
      "photochrom" not in p.lower() and "polari" not in p.lower())
check("alt text non-empty + branded", "Velluto" in ig.alt_text("x") and len(ig.alt_text("x")) <= 120)
check("slug sanitised", ig._slug("Best Cycling Glasses 2026!") == "best-cycling-glasses-2026")

# ── config ──────────────────────────────────────────────────────────────────
cfg = ig.config()
check("config has model+budget", "model" in cfg and "monthly_budget_usd" in cfg)

# ── budget guard ────────────────────────────────────────────────────────────
ig._load_gen_log = lambda: {ig._month(): {"count": 2, "cost_usd": 100.0}}
check("budget_remaining reflects spend", ig.budget_remaining() == cfg["monthly_budget_usd"] - 100.0)

# generate_cover bails when over budget (no API calls)
ig.config = lambda: {**cfg, "generate": True, "cost_per_image_usd": 0.17, "monthly_budget_usd": 1.0}
ig._load_gen_log = lambda: {ig._month(): {"count": 0, "cost_usd": 5.0}}  # spent > budget
called = {"gen": False, "spend": False}
ig.generate_image_bytes = lambda prompt: (called.__setitem__("gen", True) or b"x")
ig._record_spend = lambda c: called.__setitem__("spend", True)
res = ig.generate_cover("topic")
check("over-budget → None", res is None)
check("over-budget → no generation attempted", called["gen"] is False)

# ── generation disabled ─────────────────────────────────────────────────────
ig.config = lambda: {**cfg, "generate": False}
check("generate:false → None", ig.generate_cover("topic") is None)

# ── generation fails → None, no spend recorded, no upload ───────────────────
ig.config = lambda: {**cfg, "generate": True, "cost_per_image_usd": 0.1, "monthly_budget_usd": 99.0}
ig._load_gen_log = lambda: {}
called2 = {"spend": False, "upload": False}
ig.generate_image_bytes = lambda prompt: None
ig._record_spend = lambda c: called2.__setitem__("spend", True)
ig.upload_to_shopify_files = lambda *a, **k: called2.__setitem__("upload", True)
res = ig.generate_cover("topic")
check("gen failure → None", res is None)
check("gen failure → no spend recorded", called2["spend"] is False)
check("gen failure → no upload attempted", called2["upload"] is False)

# ── upload guard without Shopify token ──────────────────────────────────────
ig.SHOPIFY_TOKEN = ""
check("upload without token → None", ig.upload_to_shopify_files(b"x", "f.png") is None)

print("\n" + ("🎉 ALL PASSED" if not failures else f"💥 FAILED: {failures}"))
sys.exit(1 if failures else 0)
