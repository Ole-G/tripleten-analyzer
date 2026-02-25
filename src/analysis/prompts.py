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

## PRE-COMPUTED TABLES
The following tables have been calculated by code (pandas) from the raw data.
Use these EXACT numbers in your report — do NOT recalculate sums, counts, averages,
or rates yourself as your in-context arithmetic is unreliable on large datasets.
Your task is to INTERPRET and ANALYZE these pre-computed numbers, find patterns,
cross-reference between tables, and generate actionable insights.

When writing tables in your report, copy the pre-computed numbers directly.
If you need additional breakdowns not covered here, you may calculate from the
raw data below, but clearly label them as "estimated" or "approximate."

{precomputed_tables}

## RESPONSE FORMAT
Structured analytical report with:
- Executive Summary (key findings in 5 points)
- Detailed analysis for each section
- Specific numbers, blogger names, comparisons
- Tables where appropriate
- Actionable recommendations at the end

Respond in English (TripleTen team is international).

## RAW DATA (for qualitative analysis and individual case references)
{data_json}"""


TEXTUAL_REPORT_PROMPT = """\
You are a senior marketing analyst specializing in influencer marketing for EdTech.

You have been given THREE inputs:
1. **EXISTING ANALYSIS REPORT** — a comprehensive correlation analysis of 120 TripleTen \
ad integrations, covering funnel analysis, platform comparison, niche analysis, budget \
efficiency, manager performance, and high-level content scores. This report was generated \
earlier from quantitative metrics and LLM content classification scores.

2. **TEXTUAL COMPARISON** — a new, granular comparison of exact linguistic features \
between integrations WITH purchases (winners) and WITHOUT purchases (losers). This includes \
opening/closing patterns, transition styles, persuasion phrases, benefit/pain framings, \
CTA wording, specificity markers, text statistics, and more.

3. **INTEGRATION CONTEXT** — summary data for each integration that has textual analysis, \
including channel name, platform, niche, budget, purchases, and key content scores.

## YOUR TASK
Produce a **Textual Analysis Report** that:

### A. Stands alone as a valuable document
Anyone reading this report should understand the key textual findings without needing \
to read the existing report.

### B. Synthesizes with the existing report
Wherever your textual findings confirm, contradict, deepen, or nuance conclusions from \
the existing report, explicitly say so. For example:
- "The existing report identified Career niche as top-performing. Textual analysis reveals \
WHY: Career-niche winners consistently use the framing 'change your career in X months' \
rather than 'learn to code' — the career outcome framing converts 3x better."
- "The existing report noted that higher authenticity scores correlate with purchases. \
Textual analysis confirms this: winning integrations use 2.5x more first-person pronouns \
and 60% start with personal anecdotes vs 25% of losers."
- "The existing report found micro-influencers ($250-2000) have better ROI. Textual analysis \
adds a caveat: only micro-influencers who use specific price mentions ('$X per month') — \
those without specificity markers perform no better than macro."

### C. Provides CONCRETE, ACTIONABLE insights
Not "use more persuasion" but:
- Exact opening sentence templates based on winners' patterns
- Exact CTA phrases ranked by effectiveness
- Exact benefit framings to require in every brief
- Exact pain points to reference
- Word count targets
- Specific "do" and "don't" with real examples from the data

## REPORT STRUCTURE

### Executive Summary
5-7 key textual findings, each linked to a business recommendation.

### 1. Opening Patterns That Convert
- Distribution of opening types (winners vs losers), with percentages
- The winning opening hooks — quote the best ones
- Opening anti-patterns — what to avoid
- Concrete template: "Start your integration like this: ..."

### 2. Transition Styles
- How do winning bloggers transition from content to ad?
- Does acknowledging sponsorship help or hurt? Show the data.
- Best transition examples from actual integrations

### 3. Persuasion Architecture
- Which persuasion functions dominate in winners? Losers?
- Quote the most effective persuasion phrases
- Recommended persuasion stack: "A winning integration should include at minimum: ..."

### 4. Benefit Framings That Sell
- Compare exact benefit framings between groups
- Which way of describing TripleTen converts? Career change? Salary? Skills? Freedom?
- Group by theme and show conversion rates per theme

### 5. Pain Points That Resonate
- Which pain articulations appear in winners vs losers?
- Are there pain points that are overused but don't convert?

### 6. CTA Formulations
- Exact CTA phrases ranked by associated purchase rate
- Do urgency words in CTAs help?
- CTA type distribution (link_click vs consultation vs promo_code)
- The "perfect CTA" template based on data

### 7. Text Statistics & Calibration
- Optimal word count, sentence count
- You/I ratio: how much should the blogger talk about themselves vs the viewer?
- Question density: do rhetorical questions help?
- Product mention frequency: how many times to say "TripleTen"?
- Exclamation density: enthusiasm vs. cringe

### 8. Specificity as a Conversion Driver
- Do specific claims (prices, timeframes, salary numbers) correlate with purchases?
- Which specific claims appear in winners?
- Recommendation: what specificity markers should every brief include?

### 9. Cross-Reference with Existing Analysis
For each of these dimensions from the existing report, add the textual dimension:
- **Platform findings**: Do opening patterns differ between platforms? E.g. YouTube winners \
start with anecdotes, but Reels winners start with questions?
- **Niche findings**: Do textual patterns explain why certain niches convert better?
- **Budget findings**: Do cheap winning integrations have different textual patterns than \
expensive winners?
- **Manager findings**: Do different managers' bloggers use systematically different \
language patterns?
- **Top performers**: For the bloggers identified as "deserving re-order" in the existing \
report — what are their textual signatures?

### 10. The Winning Script Template
Based on ALL the data above, write a concrete script template (200-300 words) that a blogger \
could adapt. Include:
- Opening pattern
- Transition to ad
- Benefit framing
- Pain point touch
- Specificity markers
- CTA with urgency
- Closing pattern
Include 2 variants: one for YouTube (long form) and one for Reels/TikTok (short form).

### 11. Anti-Pattern Catalog
List of specific textual patterns that correlate with 0 purchases:
- Opening types to avoid
- Phrases that signal "this won't convert"
- CTA mistakes
- Missing elements (e.g., "integrations without any pain point framing never convert")

### 12. Recommendations for Brief Template
A concrete brief template that a marketing manager can send to bloggers, incorporating \
all textual findings. Include required elements, optional elements, and forbidden elements.

## FORMATTING REQUIREMENTS
- Write in English (TripleTen team is international)
- Use tables where data comparison is involved
- Quote actual phrases from the data in "quotes"
- Reference specific channels/videos by name when citing examples
- Include percentages and counts, not just qualitative statements
- Bold the most important findings

## PRE-COMPUTED TEXTUAL TABLES
The following tables have been calculated by code from the raw data.
Use these EXACT numbers in your report — do NOT recalculate sums, counts, averages,
or rates yourself as your in-context arithmetic is unreliable.
Your task is to INTERPRET and ANALYZE these pre-computed numbers.

When writing tables in your report, copy the pre-computed numbers directly.
If you need additional breakdowns not covered here, you may derive from the
comparison data below, but clearly label them as "approximate."

{precomputed_textual_tables}

## INPUTS

### EXISTING ANALYSIS REPORT
{existing_report}

### TEXTUAL COMPARISON DATA
{textual_comparison_json}

### INTEGRATION CONTEXT
{integration_context_json}
"""
