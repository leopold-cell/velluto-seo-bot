"""
Phase 5 — Performance Loop.

Closes the SEO feedback loop: read GSC per-page performance (28d vs prev 28d),
classify every URL into winner / rising / steady / decaying / dormant, and emit
a machine feed (performance_feedback.json) the decision engine consumes plus a
human/Claude-readable audit report every 28 days.

Modules:
  - classifier : GSC deltas → tiers + scale/refresh candidates → feedback json
  - audit      : 28-day-gated, Claude-readable markdown report
"""
