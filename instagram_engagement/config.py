"""
Engagement bot config — edit SEED_ACCOUNTS / LOCATION_IDS to tune discovery.

SEED_ACCOUNTS: public cycling accounts whose posts have active comment sections.
We engage with the people who COMMENT there (real active cyclists), not the
accounts themselves. Mix global media + DACH/NL/FR-relevant accounts so the
commenter pool skews toward the home markets. Use bare handles (no @).

LOCATION_IDS: optional. Instagram location page IDs — copy the number from a
location URL, e.g. instagram.com/explore/locations/213385402/stelvio-pass/
→ "213385402". Cycling hotspots (passes, velodromes) surface active riders.
Leave empty to rely on seed-account engagers only.
"""

# Tune these to your market. Handles must be public accounts.
SEED_ACCOUNTS = [
    # global cycling media / communities (large, active comment sections)
    "gcn", "gcperformance", "cyclingweekly", "bikeradar", "rouleurmagazine",
    "escapecollective", "velo", "cyclist", "roadcyclinguk",
    # relatable / community
    "velominati", "thecyclinglife", "cyclingmemes",
    # DACH / NL / FR-leaning (edit to your real target accounts)
    "tour_magazin", "rennrad_news", "wielerflits", "velo_magazine",
]

# Optional cycling-hotspot location IDs (see module docstring). Empty by default.
LOCATION_IDS: list[str] = []

# Fallback hashtags — only used if you re-enable a hashtag attempt; IG grids are
# mostly dead, kept for reference / future use.
HASHTAGS_FALLBACK = ["roadcycling", "cycling", "wielrennen", "fietsen", "cyclinggear"]
