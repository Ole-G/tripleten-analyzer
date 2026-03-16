# Methodology Redesign — Design Document

**Date:** 2026-03-16
**Goal:** Updated report for TripleTen addressing reviewer feedback
**Approach:** Parallel — enrichment re-run in background, analytics rework in parallel

---

## Context

TripleTen reviewed the initial analysis and raised 5 concerns:

1. Opaque methodology — scores appear without justification
2. LLM scoring transparency — why urgency=3 here and 7 there?
3. Statistical significance — no validation of how significant results are
4. Platform mixing — YouTube integrations vs full-video Reels/TikTok ads mixed in tables
5. Content-to-purchase correlation — too many funnel steps between video and purchase

Additional internal findings:

- 93% of enriched integrations have empty `score_details` (no reason, no evidence quotes)
- `has_contacts` as outcome variable has ceiling effect (97.5% = true) making statistical tests powerless
- Stories (24 items) included in downstream tables but have no enrichment data
- Textual report uses purchase-based winner classification, which is unreliable for content analysis

---

## Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Primary goal | Updated report for TripleTen (not reusable tool) | Immediate priority |
| Enrichment | Full re-run with multi-run ICC validation | Maximum transparency |
| Outcome variable | Two-layer: response metrics (Layer 1) + downstream descriptive (Layer 2) | Clear responsibility boundary |
| Textual report | Regenerate with response-based winner classification | Fix methodological flaw |
| TripleTen questions | Separate `reviewer_responses.md` document | Clean separation |
| Implementation approach | Parallel — enrichment background + analytics rework | Time-efficient |

---

## Deliverables

### Document 1: `analysis_report_v2.md`

Two-layer structure:

**Layer 1 — Content Impact Zone (Reach → Traffic → Contacts)**
- Continuous outcome variables: cost_per_contact, traffic_to_contact_rate, cost_per_traffic
- Quartile comparison: top 25% vs bottom 25% per-platform
- Spearman correlation between content scores and response metrics
- Per-platform tables (YouTube separate, short-form separate)
- Bootstrap CI + effect sizes (Cliff's delta) for every finding
- Power analysis for each finding

**Layer 2 — Sales Operations Context (Deals → Calls → Purchases)**
- Descriptive statistics only with clear disclaimer
- Funnel drop-off analysis
- Recommendations addressed to sales team, not content team

### Document 2: `textual_analysis_report_v2.md`

- Winners/losers classified by response metrics (cost_per_contact quartiles), not purchases
- Per-platform analysis (YouTube separate)
- Same sections as current report, rebuilt on correct classification

### Document 3: `reviewer_responses.md`

- 3 numbered answers to specific TripleTen questions
- References to data from report v2

### Supporting Artifacts

- `methodology_appendix_v2.md` — methodology with decision explanations
- `enrichment_audit_v2.csv` — full audit with score justifications
- `statistical_summary_v2.json` — machine-readable results

---

## Enrichment Pipeline Changes

### Mandatory score_details

After receiving Claude response — validate that `score_details` contains non-empty `short_reason` and `evidence_quotes` for all 8 scores. If empty — retry (up to 2 times).

### Multi-run validation (ICC)

Each integration analyzed 3 times with temperature 0.3, 0.5, 0.7:
- ICC (Intraclass Correlation Coefficient) per score dimension
- Final score = median of 3 runs
- If ICC < 0.5 for a score → marked "unstable", excluded from correlations

### Enrichment audit as first-class artifact

`enrichment_audit_v2.csv` columns per integration × score:
- score_run1, score_run2, score_run3
- final_score (median)
- icc
- short_reason, evidence_quotes (from final run)
- stability_flag: stable/moderate/unstable

### Cost estimate

88 integrations × (1 extraction + 3 analyses) = ~352 Claude calls ≈ $6-10

---

## Analytics Code Changes

### New outcome variables

| Metric | Formula | Purpose |
|--------|---------|---------|
| cost_per_contact | Budget / Contacts Fact | Cost per lead |
| traffic_to_contact_rate | Contacts / Traffic | Traffic conversion quality |
| cost_per_traffic | Budget / Traffic Fact | Cost per click |

Quartile comparison: Q1 (top 25%) vs Q4 (bottom 25%) by cost_per_contact per-platform. Gives ~14 vs 14 on YouTube instead of 49 vs 2.

### Per-platform scopes

| Scope | Contents | N | Used for |
|-------|----------|---|----------|
| youtube_only | YouTube | 51 enriched | Content score correlations, position, tone |
| short_form_only | Reels + TikTok | 37 enriched | Separate content analysis |
| all_platforms | All including Stories | 120 | Funnel and budget tables only |

Enrichment features never compared cross-platform.

### New statistical tests

Continuous outcomes:
- Spearman rank correlation (content score vs response metric, per-platform)
- Mann-Whitney U between Q1 vs Q4 groups
- Bootstrap CI for group differences
- Cliff's delta effect size

Categorical features (tone, offer_type):
- Kruskal-Wallis (comparing median cost_per_contact across categories)
- Post-hoc Dunn test if Kruskal-Wallis significant

### Power analysis

For each finding: "At current sample size (N=X) we can detect effect size Y at 80% power. To detect smaller effect, need Z integrations."

### Textual analysis reclassification

1. Compute cost_per_contact per-platform
2. Top quartile (Q1) = "high performers"
3. Bottom quartile (Q4) = "low performers"
4. Middle 50% excluded for cleaner comparison

---

## Report Generation Changes

### Updated main report prompt

- Explicit two-layer structure in prompt
- Guardrail: use continuous response metrics, never has_contacts as outcome
- Guardrail: never combine YouTube and short-form enrichment in one table
- Every finding must include: metric, effect size, CI, power statement, N
- New "Statistical Limitations" section

### Updated textual report prompt

- Response-based winner/loser classification
- Per-platform comparisons
- Guardrail: do not reference purchases when describing textual patterns

### New reviewer responses prompt

- Takes 3 questions as input
- Uses v2 report data as context
- Structure per answer: Problem → Analysis → Actionable Steps → Limitations

### Updated methodology appendix

New sections:
- "How scores were assigned" — enrichment process, rubric, ICC, stability
- "Why these outcome metrics" — rationale for cost_per_contact over has_contacts
- "Platform separation rationale"
- "What we cannot claim" — honest limitations list
