# Methodology Appendix

## Dataset Summary

- Total integrations: 1
- With traffic: 1
- With contacts: 1
- With deals: 0
- With purchases: 1

## How To Read These Tables

- `Scope` tells you which platform subset the table covers.
- `N` is the number of integrations included after filtering.
- `Outcome` tells you what success definition was used in the table.
- `Reliable signal` means the coded statistical check passed after adjustment.
- `Probable signal` means there is some evidence, but it is still uncertain.
- `Hypothesis` means the table is descriptive-only or underpowered.

## Confidence Legend

- Reliable signal: inferential test applied and adjusted p-value < 0.05.
- Probable signal: inferential test applied and adjusted p-value < 0.15.
- Hypothesis: descriptive-only or insufficient evidence.

## Guardrails

- Response outcomes are the primary layer for creative interpretation.
- Purchase outcomes are downstream and should not be framed causally.
- Small groups remain exploratory and are labeled as hypotheses.

### C1: Content Score Comparison (Response)

- Scope: `youtube_long_form`
- Population: YouTube integrations with score data; contacts-positive=1, contacts-zero=0.
- N: 1
- Outcome: `has_contacts`
- Method: Mean comparison, bootstrap 95% CI, Mann-Whitney U when both groups are large enough.
- Evidence: Hypothesis
- Caveat: Exploratory when one side has fewer than 8 scored integrations.

| Metric | With Contacts | Without Contacts | Gap | 95% CI | Evidence |
|---|---|---|---|---|---|
| specificity | 8.00 | N/A | N/A | N/A | Hypothesis |

Stat details:
- specificity: Exploratory only: need at least 8 records per group.

### C2: Offer Type and Contacts

- Scope: `youtube_long_form`
- Population: youtube_long_form rows; column `enrichment_offer_type` missing.
- N: 0
- Outcome: `has_contacts`
- Method: Descriptive only; source column missing.
- Evidence: Hypothesis
- Caveat: Column `enrichment_offer_type` is absent.

| Category | Total |
|---|---|
| No rows | N/A |

### C3: Offer Type and Contacts

- Scope: `short_form`
- Population: short_form rows; column `enrichment_offer_type` missing.
- N: 0
- Outcome: `has_contacts`
- Method: Descriptive only; source column missing.
- Evidence: Hypothesis
- Caveat: Column `enrichment_offer_type` is absent.

| Category | Total |
|---|---|
| No rows | N/A |

### C4: Offer Type and Contacts

- Scope: `cross_platform_comparable`
- Population: cross_platform_comparable rows; column `enrichment_offer_type` missing.
- N: 0
- Outcome: `has_contacts`
- Method: Descriptive only; source column missing.
- Evidence: Hypothesis
- Caveat: Column `enrichment_offer_type` is absent.

| Category | Total |
|---|---|
| No rows | N/A |

### C5: Tone and Contacts

- Scope: `youtube_long_form`
- Population: youtube_long_form rows; column `enrichment_overall_tone` missing.
- N: 0
- Outcome: `has_contacts`
- Method: Descriptive only; source column missing.
- Evidence: Hypothesis
- Caveat: Column `enrichment_overall_tone` is absent.

| Category | Total |
|---|---|
| No rows | N/A |

### C6: Tone and Contacts

- Scope: `short_form`
- Population: short_form rows; column `enrichment_overall_tone` missing.
- N: 0
- Outcome: `has_contacts`
- Method: Descriptive only; source column missing.
- Evidence: Hypothesis
- Caveat: Column `enrichment_overall_tone` is absent.

| Category | Total |
|---|---|
| No rows | N/A |

### C7: Tone and Contacts

- Scope: `cross_platform_comparable`
- Population: cross_platform_comparable rows; column `enrichment_overall_tone` missing.
- N: 0
- Outcome: `has_contacts`
- Method: Descriptive only; source column missing.
- Evidence: Hypothesis
- Caveat: Column `enrichment_overall_tone` is absent.

| Category | Total |
|---|---|
| No rows | N/A |

### C8: Personal Story and Contacts

- Scope: `cross_platform_comparable`
- Population: cross_platform_comparable rows; column `enrichment_has_personal_story` missing.
- N: 0
- Outcome: `has_contacts`
- Method: Descriptive only; source column missing.
- Evidence: Hypothesis
- Caveat: Column `enrichment_has_personal_story` is absent.

| Category | Total |
|---|---|
| No rows | N/A |

### C9: Integration Position and Contacts

- Scope: `youtube_long_form`
- Population: youtube_long_form rows; column `enrichment_integration_position` missing.
- N: 0
- Outcome: `has_contacts`
- Method: Descriptive only; source column missing.
- Evidence: Hypothesis
- Caveat: Column `enrichment_integration_position` is absent.

| Category | Total |
|---|---|
| No rows | N/A |

### R1: Response Outcomes by Platform

- Scope: `cross_platform_comparable`
- Population: All integrations grouped by platform.
- N: 1
- Outcome: `has_contacts`
- Method: Platform roll-up with a global chi-square test only when every platform bucket is sufficiently large.
- Evidence: Hypothesis
- Caveat: TikTok and any small platform bucket stay descriptive-only.

| Platform | Count | With Contacts | Total Contacts | Contact Rate | Median Cost/Contact |
|---|---|---|---|---|---|
| youtube | 1 | 1 | 10 | 100.0% | N/A |

Stat details:

### R2: Funnel Conversion Summary

- Scope: `cross_platform_comparable`
- Population: All integrations with available funnel columns.
- N: 1
- Outcome: `funnel_stage_rates`
- Method: Descriptive medians and means over row-level funnel conversion rates.
- Evidence: Hypothesis
- Caveat: Used for operational diagnostics, not for significance claims.

| Funnel Stage | Median | Mean | Non-zero |
|---|---|---|---|
| Reach -> Traffic | N/A | N/A | 0/0 |
| Traffic -> Contacts | 10.0% | 10.0% | 1/1 |
| Contacts -> Deals | 0.0% | 0.0% | 0/1 |
| Deals -> Calls | N/A | N/A | 0/0 |
| Calls -> Purchase | N/A | N/A | 0/0 |

Stat details:

### D1: Downstream Outcomes by Platform

- Scope: `cross_platform_comparable`
- Population: All integrations grouped by platform.
- N: 1
- Outcome: `has_purchases`
- Method: Platform roll-up plus a global chi-square test when the platform buckets are large enough.
- Evidence: Hypothesis
- Caveat: Treat this table as downstream association, not direct content impact.

| Platform | Count | With Purchases | Total Purchases | Purchase Rate | Winner CPP |
|---|---|---|---|---|---|
| youtube | 1 | 1 | 3 | 100.0% | $1,667 |

Stat details:

### D2: Budget Tier Downstream Summary

- Scope: `cross_platform_comparable`
- Population: All integrations grouped by `Budget Tier`.
- N: 1
- Outcome: `has_purchases`
- Method: Descriptive group roll-up with a global chi-square test when every bucket is sufficiently large.
- Evidence: Hypothesis
- Caveat: Small buckets remain exploratory; purchases are treated as downstream association only.

| Group | Count | With Purchases | Total Purchases | Purchase Rate | Winner CPP |
|---|---|---|---|---|---|
| $3,001-$5,000 | 1 | 1 | 3 | 100.0% | $1,667 |

Stat details:

### D3: Niche Downstream Summary

- Scope: `cross_platform_comparable`
- Population: All integrations grouped by `Topic`.
- N: 0
- Outcome: `has_purchases`
- Method: Descriptive group roll-up with a global chi-square test when every bucket is sufficiently large.
- Evidence: Hypothesis
- Caveat: Small buckets remain exploratory; purchases are treated as downstream association only.

| Group | Count | With Purchases | Total Purchases | Purchase Rate | Winner CPP |
|---|---|---|---|---|---|
| No rows | N/A | N/A | N/A | N/A | N/A |

### D4: Manager Downstream Summary

- Scope: `cross_platform_comparable`
- Population: All integrations grouped by `Manager`.
- N: 1
- Outcome: `has_purchases`
- Method: Descriptive group roll-up with a global chi-square test when every bucket is sufficiently large.
- Evidence: Hypothesis
- Caveat: Small buckets remain exploratory; purchases are treated as downstream association only.

| Group | Count | With Purchases | Total Purchases | Purchase Rate | Winner CPP |
|---|---|---|---|---|---|
| TestManager | 1 | 1 | 3 | 100.0% | $1,667 |

Stat details:
