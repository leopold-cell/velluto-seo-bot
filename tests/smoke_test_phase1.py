"""
Phase 1 smoke test — verifies the commercial-config wiring without spending
Anthropic tokens. Run: python3 tests/smoke_test_phase1.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- Block all Anthropic + Shopify network calls before importing seo_bot ---
captured_prompts: list[dict] = []


class FakeMessages:
    def create(self, **kwargs):
        captured_prompts.append(kwargs)
        # Return a minimal stub that mimics the response shape
        from types import SimpleNamespace
        return SimpleNamespace(
            content=[SimpleNamespace(
                text='===TITLE===\nTest\n===META===\nTest\n===BODY===\n<p>Test</p>'
            )],
            usage=SimpleNamespace(input_tokens=100, output_tokens=100),
        )


class FakeClient:
    messages = FakeMessages()


# Patch the Anthropic client before seo_bot imports
import anthropic
anthropic.Anthropic = lambda **kw: FakeClient()

# Now safe to import
from commercial_config import load_commercial_config, for_locale_short
import seo_bot

# --- Assertions ---
print("=== Phase 1 Smoke Test ===\n")

# 1. Commercial config sanity
cfg = load_commercial_config()
assert cfg["NL"]["current_price"] == 69, f"NL price wrong: {cfg['NL']}"
assert cfg["NL"]["offer_status"] == "test"
assert cfg["DE"]["current_price"] == 149
assert cfg["US"]["currency"] == "USD"
print("✅ commercial_config: NL=69 EUR (test), DE=149 EUR, US=$149")

# 2. EN-primary prompt — call generate_de_primary with stub inputs, inspect captured prompt
fake_products = [{
    "title": "Velluto StradaPro Glasses — Nero",
    "url":   "https://velluto-shop.com/products/strada-pro",
    "image": "https://cdn.shopify.com/img.jpg",
    "handle": "strada-pro",
}]
fake_kw = {"keyword": "best cycling glasses", "art_num": "099"}
fake_quality = {"day": 5, "word_count": 1800, "faq_count": 5}
captured_prompts.clear()
try:
    seo_bot.generate_de_primary(fake_kw, fake_products, fake_quality, commercial=cfg)
except Exception as e:
    # The stubbed response will fail downstream parsing — that's fine, we only care about the prompt
    pass
assert captured_prompts, "❌ generate_de_primary did not call client.messages.create"
en_prompt = captured_prompts[0]["messages"][0]["content"]
assert "€ 149" not in en_prompt, f"❌ Hard-coded € 149 still present in EN prompt!\nFound near:\n{en_prompt[en_prompt.find('€ 149')-100:en_prompt.find('€ 149')+200] if '€ 149' in en_prompt else ''}"
assert "$149" in en_prompt, f"❌ $149 missing from EN prompt"
print("✅ EN primary prompt: contains '$149', no '€ 149' leak")

# 3. NL Haiku adaptation rule
captured_prompts.clear()
fake_post = {"title": "T", "body_html": "<p>x</p>", "meta_description": "m"}
fake_market = {"keyword": "fietsbril", "intent": "commercial"}
seo_bot.generate_market_adaptation(fake_post, "nl", fake_market, commercial=cfg)
nl_system = captured_prompts[0]["system"]
assert "69 EUR" in nl_system, f"❌ NL adaptation missing '69 EUR':\n{nl_system}"
assert "test offer" in nl_system.lower(), f"❌ NL adaptation missing test-offer framing:\n{nl_system}"
print("✅ NL Haiku adaptation: contains '69 EUR' with test-offer framing")

# 4. Other locales get correct prices
locale_expectations = [
    ("de",    "149 EUR"),
    ("fr",    "149 EUR"),
    ("it",    "149 EUR"),
    ("es",    "149 EUR"),
    ("da",    "1099 DKK"),
    ("nb",    "1499 NOK"),
    ("pl",    "649 PLN"),
    ("sv",    "1599 SEK"),
    ("pt-PT", "149 EUR"),
]
for loc, expected in locale_expectations:
    captured_prompts.clear()
    seo_bot.generate_market_adaptation(fake_post, loc, fake_market, commercial=cfg)
    sys_prompt = captured_prompts[0]["system"]
    assert expected in sys_prompt, (
        f"❌ {loc} adaptation missing '{expected}':\n{sys_prompt[-400:]}"
    )
print(f"✅ All {len(locale_expectations)} other-locale adaptations contain correct local prices")

# 5. No € 149 leak anywhere in seo_bot.py source (outside comments)
import inspect
src = inspect.getsource(seo_bot)
hits = [
    line for line in src.splitlines()
    if "€ 149" in line and not line.strip().startswith("#")
]
assert not hits, "❌ Hard-coded '€ 149' lines remain in seo_bot.py:\n" + "\n".join(hits)
print("✅ Source scan: zero hard-coded '€ 149' literals remain")

print("\n🎉 Phase 1 smoke test PASSED")
