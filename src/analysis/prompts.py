"""Prompt templates for correlation analysis via Claude."""

CORRELATION_ANALYSIS_PROMPT = """\
You are a senior marketing analyst specializing in influencer marketing for EdTech.

You are given the complete dataset of TripleTen advertising integrations (JSON).
Each record contains:
- FUNNEL: reach → traffic → contacts → deals → calls → GTC → purchases
- BUDGET: integration spend ($250–$23,000)
- CONTENT (YouTube only): ad integration text + LLM analysis (tone, offer, CTA, 8 quality scores)
- METADATA: platform, blogger niche, manager, date
- CALCULATED METRICS: CPV, CPC, funnel conversion rates, etc.

Total: 120 unique integrations, of which only ~26 have purchases (Purchase F - TOTAL > 0).

## ANALYSIS TASKS

### 1. CONTENT → PURCHASES CORRELATIONS
Out of 120 integrations, only ~26 have purchases > 0. What do these 26 have in common?
- Which LLM scores (urgency, authenticity, storytelling, etc.) are highest among "winners"?
- Which offer_type dominates among integrations with purchases?
- Is there a dependency on overall_tone?
- Does has_personal_story correlate with conversion?
- Which integration_position (beginning/middle/end) is most effective?
- Compare average scores "with purchases" vs "without purchases" — where is the biggest gap?

### 2. FUNNEL: WHERE IS MONEY LOST?
- Where is the biggest drop-off in the funnel?
- Traffic→Contacts vs Contacts→Deals vs Deals→Purchase — which step is weakest?
- Does the bottleneck depend on content type or platform?
- Compare plan vs fact: which integrations overdelivered, which underdelivered? \
What is different in the content?

### 3. PLATFORMS & FORMATS
- YouTube (56) vs Reels (37) vs Stories (24) vs TikTok (3): where is the best ROI?
- Is there a conversion difference by format at the same budget level?
- Average cost_per_purchase by platform

### 4. TOPIC NICHES
22 niches (Career, Finance, Tech, Gaming, etc.):
- TOP-5 niches by conversion (purchase rate)
- TOP-5 niches by ROI (purchases / budget)
- Which niches are overvalued (high budget, few results)?

### 5. BUDGET EFFICIENCY
- Is there a budget sweet spot for maximum ROI?
- Micro-influencers ($250–2000) vs macro ($10,000+): where is the better ROI?
- "Dark horses" — low budget, high results

### 6. MANAGERS
- Compare results by manager (Masha, Arina, Tatam, etc.)
- Who selects more effective bloggers?

### 7. SUCCESS & FAILURE PATTERNS
- TOP-5 common traits of integrations with purchases
- TOP-5 common traits of integrations with 0 purchases at budget >$3000
- Specific comparison: best vs worst case (with quotes from integration_text)

### 8. ANOMALIES
- High reach but 0 traffic — why?
- Many contacts but 0 deals
- Purchases at minimal budget — what case is this?

### 9. RECOMMENDATIONS
Based on the data, formulate:
a) Ideal blogger brief (specific script template)
b) DO / DON'T checklist for new integrations
c) Recommended budget split by platforms and niches
d) 3 specific hypotheses for A/B testing
e) Which bloggers deserve re-ordering and why

## RESPONSE FORMAT
Structured analytical report with:
- Executive Summary (key findings in 5 points)
- Detailed analysis for each section
- Specific numbers, blogger names, comparisons
- Tables where appropriate
- Actionable recommendations at the end

Respond in English (TripleTen team is international).

## DATA
{data_json}"""
