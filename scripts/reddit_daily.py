#!/usr/bin/env python3
"""
Daily Reddit worklist — real open threads + a ready draft. You post, not a bot.

WHAT THIS IS NOT
It does not touch Reddit. No login, no automation, no posting. Reddit's User
Agreement prohibits automated access outside the official API, and enforcement is
behavioural (timing, headless markers, IP) rather than content-based — a script
driving a browser gets flagged however good the text is, and the penalty can
reach the DOMAIN, not just the account. Since data/seeding_targets.json ranks
reddit.com as target #1 ("AI cites it but not us"), burning it would destroy the
exact asset this is meant to build.

Threads are found through the same public web search the repo already uses for
competitor research (ddgs, see seo_optimizer.py) — reading public search results,
not scraping Reddit.

WHAT IT GIVES YOU, every morning:
  · the open threads matching the questions where AI cites Reddit instead of us
  · a draft answer, already through check_compliance
  · the Velluto article that backs it up
  · the subreddit's standing rule, so the read-check takes seconds

You decide per thread whether the answer genuinely fits — that judgement is the
part that earns upvotes, and upvoted threads are the ones AI engines cite. A
scheduled post ignores whether the thread deserves a reply, which is why
automating this produces bans instead of citations.

DISCLOSURE IS NOT OPTIONAL. Every draft carries an affiliation line. Undisclosed
brand posts are Schleichwerbung (§ 5a Abs. 4 UWG, Anhang Nr. 11 zu § 3 Abs. 3),
and most cycling subs remove them on sight. Disclosed manufacturer answers are
both legal and, in practice, welcome.

Usage:
  python3 scripts/reddit_daily.py              # today's list
  python3 scripts/reddit_daily.py --count 5
  python3 scripts/reddit_daily.py --markdown   # for the digest mail
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # noqa: E402

# Not optional. The draft path used to import link_builder, which loads the .env
# as a side effect of being imported; writing our own prompt removed that import
# and with it the credentials. The run then picked up a stale ANTHROPIC_API_KEY
# from the shell environment and every draft came back 401. override=True because
# that stale value is exactly what has to lose.
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
            override=True)

DEFAULT_COUNT = 3

# geo_gaps normalises every market to a language code (us/gb/au → en, at/ch → de,
# be → nl), so gap["market"] IS the language the reply has to be written in. The
# first working run appended a German link sentence to an English r/cycling post —
# in a sub where a non-native-looking promo line is exactly what gets removed.
LANG_NAME = {"en": "English", "de": "German", "nl": "Dutch", "fr": "French"}

DISCLOSURE = {
    "en": "Disclosure: I build Velluto, so take this with the appropriate pinch of salt.",
    "de": "Offenlegung: Ich baue Velluto — entsprechend einzuordnen.",
    "nl": "Openheid: ik maak Velluto, dus neem dit met een korrel zout.",
    "fr": "Transparence : je fabrique Velluto, à prendre avec le recul qui s'impose.",
}

LINK_LINE = {
    "en": "I wrote the details up here: {url}",
    "de": "Die Details habe ich hier aufgeschrieben: {url}",
    "nl": "De details heb ik hier opgeschreven: {url}",
    "fr": "J'ai détaillé tout ça ici : {url}",
}

# Standing rules per subreddit — shown with every thread so the read-check is quick.
SUB_RULES = {
    "cycling":        "No self-promotion. Only answer if the reply works without the link.",
    "bicycling":      "As r/cycling — promotional posts get removed.",
    "RoadCycling":    "Smaller, tolerant of detail. Experience before link.",
    "gravelcycling":  "Genuine gravel topics only.",
    "wielrennen":     "Write Dutch. Small community, promotion is obvious.",
    "Fahrrad":        "Auf Deutsch schreiben. Werbung fällt sofort auf.",
    "Velo":           "Technical questions welcome, disclose affiliation.",
    "velo":           "Technical questions welcome, disclose affiliation.",
    "MTB":            "Off-road context. A road-eyewear answer is off-topic here.",
    "cyclocross":     "Small and expert. Mud/fog specifics or nothing.",
    "bicycletouring": "Long-distance context; day-racing answers miss the point.",
    "bikewrench":     "Repair questions. Eyewear is almost always off-topic.",
    "brompton":       "Folding bikes, commuting. Rarely an eyewear thread.",
    "xbiking":        "Anti-consumerist by temperament — a brand mention lands badly.",
    "peloton":        "Indoor training. Outdoor eyewear is usually off-topic.",
    "Zwift":          "Indoor training. Outdoor eyewear is usually off-topic.",
    "TrainerRoad":    "Training methodology, not gear shopping.",
    "triathlon":      "Fit under a helmet and in transition is what matters here.",
}


# Only these subreddits count. The unfiltered search returned r/enail (a vaping
# sub — "eyesmoke glassware incycler" matched on "glass") and r/Anbennar (a
# Europa Universalis mod). A generic question like "Do I need cycling glasses?"
# pulls anything containing the words, so relevance has to be asserted, not hoped
# for. An off-topic post is worse than no post: it gets removed and marks the
# account as a spammer.
#
# r/glasses and r/optometry were in this list — my mistake. They are eyewear subs,
# but for PRESCRIPTION and optical eyewear, which we do not make. They pulled in
# "Spent 600$ on two pairs of glasses" and "Just paid $600 for prescription ray
# bans", and a €69 sport-sunglasses maker answering those is a price-anchoring
# pitch in a category we cannot serve. Same subreddit, different product.
ALLOWED_SUBS = {
    "cycling", "bicycling", "RoadCycling", "gravelcycling", "Velo", "bikewrench",
    "cyclocross", "MTB", "bicycletouring", "brompton", "xbiking", "peloton",
    "Zwift", "TrainerRoad", "triathlon", "wielrennen", "Fahrrad", "velo",
}

# The r/glasses hits showed "Regel: Subreddit-Regeln vor dem Posten prüfen" — a
# non-answer where the standing rule belongs, because the allowlist and the rule
# table were maintained separately and drifted. This makes the drift loud.
_NO_RULE = sorted(s for s in ALLOWED_SUBS if s not in SUB_RULES)
if _NO_RULE:
    print(f"   ⚠️  Subreddits ohne Regel-Eintrag: {', '.join(_NO_RULE)}")


# The right subreddit is not yet the right thread. "Do I need cycling glasses?"
# returned r/cycling/comments/…/how_do_i_stop_my_balls_from_hurting_so_much_on/ —
# correct sub, and about saddle discomfort. Answering there with an eyewear reply
# is the drive-by promo that gets comments removed, so the thread itself has to be
# about eyewear.
_EYEWEAR = ("glasses", "sunglass", "sunnies", "shades", "eyewear", "goggle",
            "lens", "lenses", "visor", "optic", "bril", "brille", "occhiali",
            "lunettes", "gafas")


def _is_eyewear_thread(title: str, url: str) -> bool:
    """Search titles are unreliable — two of the hits came back as the literal
    string "Link to reddit.com". The URL slug carries the real thread title
    (…/comments/1dsxotd/how_do_i_stop_my_balls_from_hurting_so_much_on/), so read
    both and let either one qualify the thread."""
    slug = re.sub(r"[^a-z]+", " ", url.rsplit("/comments/", 1)[-1].lower())
    blob = f"{(title or '').lower()} {slug}"
    return any(w in blob for w in _EYEWEAR)


def _threads_for(question: str, limit: int = 3) -> list[dict]:
    """Open Reddit threads on this topic, via public web search."""
    try:
        from ddgs import DDGS
    except ImportError:
        return []
    out = []
    try:
        with DDGS() as d:
            for hit in d.text(f"site:reddit.com {question}", max_results=limit * 4):
                url = hit.get("href") or hit.get("url") or ""
                m = re.search(r"reddit\.com/r/([A-Za-z0-9_]+)/comments/", url)
                if not m:
                    continue
                if m.group(1).lower() not in {x.lower() for x in ALLOWED_SUBS}:
                    continue      # off-topic sub — see ALLOWED_SUBS
                title = (hit.get("title") or "").strip()[:110]
                if not _is_eyewear_thread(title, url):
                    continue      # right sub, wrong topic — see _is_eyewear_thread
                out.append({"url": url.split("?")[0], "sub": m.group(1),
                            "title": title or url.rsplit("/comments/", 1)[-1]
                                              .split("/")[-1].replace("_", " ")[:110]})
                if len(out) >= limit:
                    break
    except Exception as e:
        print(f"   ⚠️  thread search failed: {e}")
    return out


# Features Velluto does not sell. check_brand_facts() only flags them when the
# same SENTENCE attributes them to Velluto, which is the right call for an article
# — discussing photochromic lenses informatively is legitimate. A Reddit reply is
# shorter and comes from the maker, so "decide if you want photochromic…" two
# lines above "I ride Velluto" reads as a spec claim even across sentences.
# Too ambiguous to block (it would flag honest comparisons), too risky to ignore:
# it becomes a note on the human's read-check, which is what this list is for.
_ABSENT_FEATURES = ("photochrom", "polari", "prescription", "varifocal", "mirrored")


def _feature_proximity(body: str) -> list[str]:
    low = (body or "").lower()
    if "velluto" not in low:
        return []
    return [f"erwähnt „{f}“ — Velluto bietet das nicht an; sicherstellen, dass der "
            f"Satz es nicht Velluto zuschreibt"
            for f in _ABSENT_FEATURES if f in low]


# link_builder's prompt was written for the automated poster that never ran. It
# says the post must "feel like a real cyclist ASKING or sharing" and to mention
# Velluto — which produced a draft opening "I'm looking for recommendations…" and
# closing "Has anyone found a sweet spot?" while plugging the StradaPro. The maker
# pretending to seek advice is astroturfing, and the disclosure line does not cure
# it: the framing itself is the lie.
#
# A disclosed reply from the maker has exactly one honest shape: answer the
# question that was asked, say who you are, and stop.
_DRAFT_PROMPT = """You are the founder of Velluto, replying in a Reddit thread on r/{sub}.
Write in {language}. Your affiliation is disclosed automatically, so write as
yourself — never as a neutral cyclist, and NEVER ask for recommendations or
opinions: you make the product, so asking would be dishonest.

The thread question: {question}

Write a reply of 120-180 words that:
- answers that question directly in the first two sentences, useful even to
  someone who never buys anything
- names the criteria that actually decide it (weight, coverage, ventilation,
  lens standard, fit) so the reader can judge any pair, not just ours
- mentions Velluto in ONE sentence, 25 words at most, and only with specs we can
  evidence: 25 g, UV400-certified, tool-free interchangeable lenses, built-in
  anti-fog, 30-day trial, from 69 EUR. Delete that sentence and the reply must
  still fully answer the question — that is r/{sub}'s actual rule, and a
  paragraph-long product pitch gets the comment removed.
- NEVER mentions photochromic, polarised, prescription or mirrored lenses in any
  way that could read as a Velluto feature — we do not sell them
- never claims a test, ranking or comparison we did not run
- makes no superiority claim over a named brand
- contains NO disclosure, disclaimer or "I founded Velluto" line. One is appended
  for you; writing your own produces two.
- ends on the answer. Do NOT close by asking the reader what matters to them or
  what they are looking for — from the maker that reads as lead qualification,
  not conversation.

Output EXACTLY:
TITLE: <short title>
BODY:
<body text>"""


# The model wrote "*Full disclosure: I founded Velluto.*" on top of the appended
# line, so the first working drafts carried two. The prompt now forbids it, but a
# prompt is a request, not a guarantee — and a doubled disclosure is the kind of
# detail that makes a post read as machine-written. Only the last few lines are
# considered, so an identical phrase mid-argument survives.
_SELF_DISCLOSURE = re.compile(
    r"^\s*[*_>\s]*(?:full\s+)?(?:disclosure|disclaimer|offenlegung|transparence|openheid)\b"
    r"|^\s*[*_>\s]*i(?:'m| am)?\s+(?:the\s+)?(?:founded|found|founder|build|make|run|own)\b[^.]{0,40}velluto",
    re.I)


def _strip_self_disclosure(body: str) -> str:
    """Also drops the horizontal rule the model puts above its disclosure — the
    first cleaned draft ended on a bare "---" once the line beneath it was gone."""
    lines = (body or "").rstrip().splitlines()
    while lines and (not lines[-1].strip()
                     or _SELF_DISCLOSURE.search(lines[-1])
                     or re.fullmatch(r"\s*[-*_]{3,}\s*", lines[-1])):
        lines.pop()
    return "\n".join(lines).rstrip()


def _skeleton(question: str, url: str, reason: str, lang: str) -> tuple[str, str]:
    """A structured draft the human can finish by hand. Better than the raw API
    error the run pasted into both drafts — that made the worklist useless on the
    one day it was needed.

    The scaffolding stays German: it is a note to you, not part of the post. The
    link line does not, because that one gets posted.
    """
    body = (f"[Rohentwurf — {reason}]\n"
            f"Frage: {question}\n"
            f"Sprache: {LANG_NAME.get(lang, 'English')}\n"
            "Aufbau: Frage direkt beantworten → Kriterien nennen (Gewicht, Abdeckung, "
            "Belüftung, Linsennorm, Passform) → Velluto in EINEM Satz, nur mit "
            "belegbaren Specs.")
    if url:
        body += "\n\n" + LINK_LINE.get(lang, LINK_LINE["en"]).format(url=url)
    return question, body


# One dead key must not produce one error per draft. Once auth has failed the key
# will not recover mid-run, so the rest of the list skips the API entirely.
_AUTH_DEAD = False


def _draft_text(question: str, url: str, sub: str, lang: str = "en") -> tuple[str, str]:
    global _AUTH_DEAD
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        return _skeleton(question, url, "kein ANTHROPIC_API_KEY gesetzt", lang)
    if _AUTH_DEAD:
        return _skeleton(question, url, "ANTHROPIC_API_KEY ungültig", lang)
    try:
        from anthropic import Anthropic
        r = Anthropic(api_key=key).messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=600,
            messages=[{"role": "user",
                       "content": _DRAFT_PROMPT.format(
                           sub=sub, question=question,
                           language=LANG_NAME.get(lang, "English"))}])
        raw = r.content[0].text.strip()
        t = re.search(r"TITLE:\s*(.+)", raw)
        b = re.search(r"BODY:\s*([\s\S]+)", raw)
        title = t.group(1).strip() if t else question
        body = _strip_self_disclosure(b.group(1).strip() if b else raw)
    except Exception as e:
        msg = str(e)
        if "authentication" in msg.lower() or "401" in msg:
            _AUTH_DEAD = True
            print("   ⚠️  ANTHROPIC_API_KEY wird abgelehnt (401) — Entwürfe bleiben "
                  "Rohentwürfe. Key in .env prüfen; danach erneut laufen lassen.")
            return _skeleton(question, url, "ANTHROPIC_API_KEY ungültig", lang)
        return _skeleton(question, url, f"Entwurf fehlgeschlagen: {msg[:90]}", lang)
    # Only link a real article. The old fallback linked the shop homepage when no
    # article matched — a bare shop link in r/cycling is removed as advertising.
    if url:
        body += "\n\n" + LINK_LINE.get(lang, LINK_LINE["en"]).format(url=url)
    return title, body


# Asking for advice while selling the thing is the astroturf pattern, and it is
# invisible to the legal gate — every individual sentence is true.
_ASKING_RE = re.compile(
    r"\b(looking for recommendations|any recommendations|what do you (?:use|recommend)"
    r"|has anyone (?:found|tried)|curious what|suggestions\?|thoughts\?)", re.I)


def _sounds_like_asking(body: str) -> list[str]:
    if not re.search(r"\bvelluto\b", body or "", re.I):
        return []
    m = _ASKING_RE.search(body or "")
    return ([f"fragt nach Empfehlungen („{m.group(0)}“) und nennt zugleich Velluto — "
             f"das wirkt wie ein gestellter Beitrag; umformulieren als offene Antwort"]
            if m else [])


def _thread_traps(threads: list[dict]) -> list[str]:
    """A thread can be on-topic and still be the wrong place for us. The search
    surfaced "does anybody ride with photochromic sunglasses" — eyewear, r/cycling,
    and about the one thing we do not sell. Answering it as the maker means either
    going off-topic or implying we offer it. Worth knowing before you open the tab;
    an honest "we don't do photochromic, here is what decides it" is a fine reply,
    a careless one is a false product claim."""
    out = []
    for t in threads:
        blob = f"{t.get('title', '')} {t.get('url', '')}".lower()
        for f in _ABSENT_FEATURES:
            if f in blob:
                out.append(f"Thread dreht sich um „{f}…“ — das führen wir nicht. "
                           f"Nur antworten, wenn die Antwort das offen sagt: {t['url']}")
                break
    return out


def build(count: int = DEFAULT_COUNT) -> list[dict]:
    from geo_gaps import collect_gaps
    from reddit_drafts import _live_article_for
    try:
        from briefs.quality_gate import check_compliance, check_brand_facts
    except Exception:
        check_compliance = check_brand_facts = None

    # Only questions where AI cites Reddit and not us — that is the whole point.
    gaps = collect_gaps()
    candidates = []
    for market, rows in gaps.items():
        for r in rows:
            if any("reddit" in d for d in r.get("rivals", [])):
                candidates.append({**r, "market": market})
    candidates.sort(key=lambda r: -r["misses"])

    items = []
    for gap in candidates:
        if len(items) >= count:
            break
        q = gap["question"]
        threads = _threads_for(q, limit=2)
        if not threads:
            continue
        lang = gap["market"] if gap["market"] in LANG_NAME else "en"
        url = _live_article_for(q)
        title, body = _draft_text(q, url, threads[0]["sub"], lang)
        body = f"{body}\n\n{DISCLOSURE.get(lang, DISCLOSURE['en'])}"
        # check_compliance covers the advertising-law rules but NOT the product
        # facts. The first live run produced drafts mentioning "polarized" and
        # "photochromic" a line away from "I've been riding some Velluto frames" —
        # features Velluto does not sell. On Reddit that reads as a spec claim from
        # the maker, which is worse than on the blog: it is a direct answer to a
        # buyer. check_brand_facts() is the gate that catches it.
        issues = check_compliance({"title": title, "body_html": body}) if check_compliance else []
        if check_brand_facts:
            issues += check_brand_facts({"body_html": body})
        notes = _feature_proximity(body) + _sounds_like_asking(body) + _thread_traps(threads)
        items.append({"question": q, "market": gap["market"], "misses": gap["misses"],
                      "threads": threads, "draft_title": title, "draft_body": body,
                      "source": url, "legal_issues": issues, "notes": notes})
    return items


def render(items: list[dict], markdown: bool = False) -> str:
    if not items:
        return ("Reddit-Tagesliste: keine passenden offenen Threads gefunden. "
                "Entweder fehlen Messläufe (geo_gaps braucht 2+) oder die Suche lieferte nichts.")
    L = [f"Reddit-Tagesliste ({len(items)}) — du postest, nichts läuft automatisch", ""]
    for i, it in enumerate(items, 1):
        L.append(f"── #{i}  [{it['market'].upper()}]  KI zitiert hier Reddit, uns nicht "
                 f"({it['misses']}× verfehlt)")
        L.append(f"   Frage: {it['question']}")
        L.append("   Offene Threads:")
        for t in it["threads"]:
            rule = SUB_RULES.get(t["sub"], "Subreddit-Regeln vor dem Posten prüfen.")
            L.append(f"     • r/{t['sub']} — {t['title']}")
            L.append(f"       {t['url']}")
            L.append(f"       Regel: {rule}")
        if it["legal_issues"]:
            L.append("   ⛔ NICHT POSTEN — Legal-Gate:")
            for x in it["legal_issues"]:
                L.append(f"      {x[:110]}")
        for n in it.get("notes", []):
            L.append(f"   ⚠️  PRÜFEN: {n}")
        L.append("   Entwurf:")
        for line in (it["draft_body"] or "").splitlines():
            L.append(f"      {line}")
        L.append(f"   Quelle: {it['source'] or '— kein passender Artikel'}")
        L.append("")
    L.append("Vorgehen: Thread lesen → passt die Antwort wirklich? → Entwurf anpassen → "
             "posten. Lieber keinen Beitrag als einen unpassenden.")
    return "\n".join(L)


OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "output", "reddit_daily.txt")


def _int_arg(flag: str, default: int) -> int:
    """Numeric CLI flag that tolerates a typo instead of dying on it.

    Hand-rolled int(sys.argv[i+1]) raised ValueError on "--count 2." — a stray
    period copied out of prose. A tracebacked script reads like a broken tool;
    it is not, and the run should continue with the default.
    """
    if flag not in sys.argv:
        return default
    i = sys.argv.index(flag)
    if i + 1 >= len(sys.argv):
        print(f"   ⚠️  {flag} without a value — using {default}")
        return default
    raw = sys.argv[i + 1].strip().rstrip(".,;")
    try:
        return max(1, int(raw))
    except ValueError:
        print(f"   ⚠️  {flag} expects a number, got {sys.argv[i + 1]!r} — using {default}")
        return default


def main() -> None:
    count = _int_arg("--count", DEFAULT_COUNT)
    text = render(build(count), markdown="--markdown" in sys.argv)
    print(text)
    # Written to disk so the daily mail can include it without re-running the
    # search — daily_report must not depend on network calls.
    try:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        print(f"   ⚠️  could not write {OUT}: {e}")


if __name__ == "__main__":
    main()
