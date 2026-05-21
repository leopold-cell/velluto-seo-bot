"""
Velluto SEO Bot — Deutsche Keyword-Queue (primärer Content-Kalender)
Longtail DE-Keywords treiben den Artikel-Rhythmus.
NL + EN bekommen eigene marktspezifische Adaptionen.
"""

import json, os

_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "de_keywords_used.json")

DE_KEYWORD_QUEUE = [
    # ── Phase 1: Long-tail, geringer Wettbewerb ──────────────────────────────
    {
        "keyword": "fahrradbrille für brillenträger",
        "volume": 500, "phase": 1,
        "angle": "Problem: Druckpunkte + schlechter Sitz normaler Sonnenbrillen über Korrekturbrillen. "
                 "Lösung: Wraparound-Rahmen mit verstellbaren Nasenpads + minimalem Gewicht. "
                 "USP: StradaPro 25g, verstellbare Nasenpads, Anti-Fog, passt über die meisten Monturen. "
                 "30-Tage-Probefahrt.",
    },
    {
        "keyword": "fahrradbrille mit wechselgläsern",
        "volume": 200, "phase": 1,
        "angle": "USP Velluto: Click-In Wechselgläser in Sekunden. Use Cases: klares Glas für Regen/Nacht, "
                 "getöntes für Sonne. VellutoVisione™ und VellutoPuro im Vergleich. "
                 "Warum Wechselgläser den Kauf von zwei Brillen ersetzen.",
    },
    {
        "keyword": "fahrradbrille gegen tränende augen",
        "volume": 100, "phase": 1,
        "angle": "Ursache: Wind, Pollen, UV-Strahlung. Wraparound-Design schützt von der Seite. "
                 "Anti-Beschlag verhindert Sichteinschränkung. UV400 schützt empfindliche Augen. "
                 "Konkrete Situationen: Gefälle, Gegenwind, Frühjahrstouren.",
    },
    {
        "keyword": "leichte rennradbrille",
        "volume": 200, "phase": 1,
        "angle": "Warum Gewicht bei Rennradbrillen zählt: Druckgefühl nach 3h, Rutschgefahr, Aerodynamik. "
                 "StradaPro 25g vs. typische Konkurrenz 40-60g. Materialvergleich: TR-90 vs. Polycarbonat. "
                 "Schwerpunkt: Langstrecke + Kletterer.",
    },
    {
        "keyword": "rennradbrille damen",
        "volume": 300, "phase": 1,
        "angle": "Spezifische Anforderungen: schmäleres Nasenpad, leichteres Gestell, kleinere Schläfen. "
                 "StradaPro Varianten: Viola, Arancia. Pasvorm-Tipps. Keine extra 'Damen-Brille' nötig — "
                 "warum das Verstellsystem universell funktioniert.",
    },
    {
        "keyword": "fahrradbrille mtb test",
        "volume": 300, "phase": 1,
        "angle": "MTB-Anforderungen: Seiten­schutz, Anti-Beschlag, Haltbarkeit. Vergleich mit Road. "
                 "Wechselgläser-Vorteil: Wald/Schatten vs. offene Trails. "
                 "StradaPro auf Gravel- und MTB-Strecken getestet.",
    },
    {
        "keyword": "fahrradbrille gravel",
        "volume": 200, "phase": 1,
        "angle": "Gravel-spezifisch: wechselnde Lichtbedingungen, Staub, langer Horizont. "
                 "Wechselgläser als Lösung. Sitzt auch nach 6h noch? Gewicht + Pasvorm im Fokus. "
                 "Gardasee/Alpen-Kontext passend zu Velluto.",
    },
    {
        "keyword": "photochrome fahrradbrille test",
        "volume": 500, "phase": 1,
        "angle": "Photochrom vs. Wechselgläser: Reaktionszeit, Tunnel/Wald-Problem, Gewicht. "
                 "Wann photochrom Sinn macht, wann nicht. "
                 "VellutoPuro (klar) + VellutoVisione (getönt) als manuelle Alternative erklärt.",
    },
    {
        "keyword": "rennradbrille beschlägt nicht",
        "volume": 100, "phase": 1,
        "angle": "Ursache Beschlag: Temperaturunterschied, Anstieg, Regen. "
                 "Anti-Fog-Beschichtung + Belüftungsschlitze erklärt. "
                 "StradaPro Anti-Fog im Praxistest. Tipps: Reinigung, Atemführung.",
    },
    {
        "keyword": "fahrradbrille uv schutz",
        "volume": 200, "phase": 1,
        "angle": "Was UV400 bedeutet: 100% UVA + UVB. Warum normale Sonnenbrillen nicht reichen (< 100%). "
                 "Langzeitfolgen ohne Schutz. StradaPro UV400-Zertifizierung. "
                 "Hochgebirge, Gardasee-Sommer, Frühling.",
    },
    {
        "keyword": "fahrradbrille triathlon",
        "volume": 100, "phase": 1,
        "angle": "Anforderungen Triathlon: schnell umziehen T1/T2, leicht, beschlägt nicht beim Laufen. "
                 "25g + Wechselgläser für Swim-to-Bike. Keine Polarisation wegen Wasseroberfläche. "
                 "StradaPro Nero als neutrales, vielseitiges Modell.",
    },
    {
        "keyword": "rennradbrille polarisiert oder nicht",
        "volume": 100, "phase": 1,
        "angle": "Fachthema: Polarisation filtert horizontale Reflexionen aber verdeckt LCD-Displays "
                 "(Garmin, Shimano Di2). Warum Top-Rennradfahrer keine polarisierten Gläser nutzen. "
                 "VellutoVisione™ ohne Polarisation — bewusste Entscheidung erklärt.",
    },
    {
        "keyword": "fahrradbrille nachts fahren",
        "volume": 100, "phase": 1,
        "angle": "Klare Gläser als Schutz: Wind, Insekten, Kälte. VellutoPuro (klar) Use Case. "
                 "Wichtig: kein Tönung die Sicht reduziert. Anti-Beschlag bei Kälte + Tunneln. "
                 "Pendler + Abendtraining als Zielgruppe.",
    },
    {
        "keyword": "sportbrille für radfahrer",
        "volume": 300, "phase": 1,
        "angle": "Unterschied Sportbrille vs. normale Sonnenbrille für Radfahrer: Wrap-around, "
                 "Nasenpads, Gummibügel, Anti-Beschlag. Warum günstige Sportbrillen beim Radfahren versagen. "
                 "StradaPro als Premium-Einstieg erklärt.",
    },
    {
        "keyword": "fahrradbrille oakley alternative",
        "volume": 200, "phase": 1,
        "angle": "Direkter Vergleich: Oakley Jawbreaker (€250) vs. Velluto StradaPro (€149). "
                 "Gewicht, Wechselgläser, Passform, Preis-Leistung. "
                 "Für wen lohnt sich der Aufpreis? Für wen nicht?",
    },

    # ── Phase 2: Mittleres Volumen ────────────────────────────────────────────
    {
        "keyword": "beste fahrradbrille 2026",
        "volume": 1000, "phase": 2,
        "angle": "Pillar: Top-5 Fahrrradbrillen getestet. Kriterien: Gewicht, UV, Anti-Fog, Preis. "
                 "StradaPro als bestes Preis-Leistungs-Modell. Vergleichstabelle. "
                 "Für Rennrad, Gravel, MTB je eine Empfehlung.",
    },
    {
        "keyword": "fahrradbrille kaufen",
        "volume": 2000, "phase": 2,
        "angle": "Kaufberatung: 5 Kriterien die zählen (UV, Anti-Fog, Gewicht, Wechselgläser, Passform). "
                 "Häufige Fehler beim Kauf. Preisklassen erklärt. "
                 "StradaPro als konkrete Empfehlung mit 30-Tage-Rückgabe.",
    },
    {
        "keyword": "rennradbrille verspiegelt",
        "volume": 500, "phase": 2,
        "angle": "Warum verspiegelte Gläser? Optik + Funktion (reflektiert Wärme). "
                 "VellutoVisione™ leicht verspiegelt für Sommer. Unterschied verspiegelt vs. polarisiert. "
                 "Welche Farbe für welches Wetter.",
    },
    {
        "keyword": "sportbrille radsport test",
        "volume": 500, "phase": 2,
        "angle": "Marktüberblick: Uvex, Oakley, Rudy Project, Velluto im Vergleich. "
                 "Testkriterien: Stabilität bei 60 km/h, Beschlag auf Kletter, Sitz nach 4h. "
                 "Ehrliche Stärken + Schwächen.",
    },
    {
        "keyword": "fahrradbrille für kurzsichtige",
        "volume": 500, "phase": 2,
        "angle": "Kurzsichtige auf dem Rad: Kontaktlinsen + Schutzbrille vs. OTG-Lösung. "
                 "Vor- und Nachteile beider Ansätze. StradaPro OTG Passform. "
                 "Tipp: Kontaktlinsen + Velluto für beste Kombi.",
    },
    {
        "keyword": "fahrradbrille kinder",
        "volume": 300, "phase": 2,
        "angle": "Warum Kinderfabrradbrillen wichtig sind (UV-Schäden beginnen früh). "
                 "Wichtige Kriterien: Bruchsicherheit, Passform, verstellbar. "
                 "Velluto Junior (falls vorhanden) oder alternative Empfehlungen.",
    },

    # ── Phase 3: Hohe Volumen / Pillar Content ────────────────────────────────
    {
        "keyword": "fahrradbrille",
        "volume": 5000, "phase": 3,
        "angle": "Der ultimative Fahrradbrille-Guide 2026. Alles was Radfahrer wissen müssen: "
                 "Typen, Gläser, Materialien, Pflege. StradaPro als zentrale Empfehlung. "
                 "Für Einsteiger + Fortgeschrittene. Interne Links zu allen Cluster-Artikeln.",
    },
    {
        "keyword": "rennradbrille",
        "volume": 5000, "phase": 3,
        "angle": "Kompletter Rennradbrille-Guide: Aerodynamik, Gewicht, Wechselgläser, UV. "
                 "Unterschied zum MTB. Top-Empfehlungen 2026. StradaPro im Mittelpunkt. "
                 "Pillar-Seite mit internen Links.",
    },
    {
        "keyword": "fahrradbrille test",
        "volume": 3000, "phase": 3,
        "angle": "Großer Fahrradbrille-Test 2026: 8 Modelle getestet über 500+ km. "
                 "Testprotokoll, Bewertungsmatrix, Fotos. StradaPro Testsieger Preis/Leistung. "
                 "Ehrlicher Vergleich inkl. Schwächen.",
    },
    {
        "keyword": "sportbrille fahrrad",
        "volume": 2000, "phase": 3,
        "angle": "Was macht eine Brille zur echten Sportbrille fürs Rad? "
                 "Unterschiede normale Sonnenbrille vs. Sportbrille. "
                 "Top 5 Modelle. StradaPro als Empfehlung.",
    },
]


def _load_used() -> set:
    if not os.path.exists(_LOG):
        return set()
    return set(json.load(open(_LOG)))


def _save_used(used: set):
    json.dump(sorted(used), open(_LOG, "w"), indent=2)


def get_next_de_keyword() -> dict | None:
    """Return the next unused DE keyword, lowest phase first, highest volume first within phase."""
    used = _load_used()
    remaining = [k for k in DE_KEYWORD_QUEUE if k["keyword"] not in used]
    if not remaining:
        return None
    remaining.sort(key=lambda k: (k["phase"], -k["volume"]))
    return remaining[0]


def mark_de_keyword_used(keyword: str):
    used = _load_used()
    used.add(keyword)
    _save_used(used)


def get_de_queue_status() -> dict:
    used = _load_used()
    by_phase: dict[str, dict] = {}
    for k in DE_KEYWORD_QUEUE:
        p = str(k["phase"])
        if p not in by_phase:
            by_phase[p] = {"total": 0, "done": 0}
        by_phase[p]["total"] += 1
        if k["keyword"] in used:
            by_phase[p]["done"] += 1
    return {
        "total": len(DE_KEYWORD_QUEUE),
        "used":  len(used),
        "by_phase": by_phase,
    }
