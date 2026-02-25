"""Prompt templates for LLM enrichment of ad integration transcripts."""

EXTRACT_INTEGRATION_PROMPT = """\
You are an expert at analyzing YouTube video transcripts to identify \
advertising integration segments for TripleTen (an online tech education platform).

You will receive a full video transcript with timestamps and optionally a hint \
timestamp indicating approximately where the ad integration begins.

Your task: identify and extract the exact ad integration segment from the transcript.

## Input
- Full transcript (list of segments with "text", "start", "duration" fields)
- Integration timestamp hint: {integration_timestamp} seconds (may be "unknown" if not available)

## Transcript
{transcript_json}

## Instructions
1. Find the ad integration / sponsored segment about TripleTen in the transcript.
2. If a timestamp hint is provided, focus on the area around that timestamp \
(typically within 120 seconds), but adjust boundaries to capture the complete integration.
3. If no timestamp hint is available, scan the full transcript for sponsored/ad \
content — look for mentions of TripleTen, calls to action, discount codes, \
links in description, career change pitch, etc.
4. Extract the complete text of the integration segment.
5. Determine if the entire video is essentially an ad (e.g., a dedicated review \
or promotional video for TripleTen).

## Response format
Return ONLY a valid JSON object with these exact fields:
{{
    "integration_text": "<full text of the ad integration segment>",
    "integration_start_sec": <start time in seconds as number>,
    "integration_duration_sec": <duration of integration in seconds as number>,
    "integration_position": "<one of: beginning, middle, end>",
    "is_full_video_ad": <true if the entire video is essentially an ad, false otherwise>
}}

Return ONLY the JSON object, no additional text or markdown fencing."""


ANALYZE_INTEGRATION_PROMPT = """\
You are an expert marketing analyst specializing in influencer ad integrations \
for EdTech products (specifically TripleTen).

Analyze the following ad integration text from a YouTube video and extract \
structured content characteristics.

## Integration text
{integration_text}

## Instructions
Analyze the text and classify it across all dimensions below. Be precise and \
evidence-based — only mark features as present if they are clearly in the text.

## Response format
Return ONLY a valid JSON object with these exact fields:
{{
    "offer_type": "<one of: discount, promo_code, free_consultation, free_trial, free_course, other>",
    "offer_details": "<brief description of the specific offer>",
    "landing_type": "<one of: programs_page, free_consultation, specific_course>",
    "cta_type": "<one of: link_in_description, promo_code, qr_code, swipe_up, direct_link>",
    "cta_urgency": "<one of: none, low, medium, high>",
    "cta_text": "<exact call-to-action phrase used>",
    "has_personal_story": <true or false>,
    "personal_story_type": "<one of: career_change, learning_experience, friend_recommendation, none>",
    "pain_points_addressed": ["<list of specific pain points mentioned>"],
    "benefits_mentioned": ["<list of specific product benefits mentioned>"],
    "objection_handling": <true or false>,
    "social_proof": "<one of: none, testimonial, statistics, celebrity>",
    "scores": {{
        "urgency": <1-10>,
        "authenticity": <1-10>,
        "storytelling": <1-10>,
        "benefit_clarity": <1-10>,
        "emotional_appeal": <1-10>,
        "specificity": <1-10>,
        "humor": <1-10>,
        "professionalism": <1-10>
    }},
    "overall_tone": "<one of: enthusiastic, casual, professional, skeptical_converted, educational>",
    "language": "<detected language code, e.g. en, es, uk, ru>",
    "product_positioning": "<one of: career_change, upskill, side_income, tech_entry, general_education>",
    "target_audience_implied": "<brief description of the implied target audience>",
    "competitive_mention": <true or false>,
    "price_mentioned": <true or false>
}}

Return ONLY the JSON object, no additional text or markdown fencing."""


TEXTUAL_ANALYSIS_PROMPT = """\
You are a linguistic analyst specializing in persuasion and advertising copy.

Analyze the following ad integration text from an influencer video promoting \
TripleTen (an online tech education platform). Extract granular textual features \
that can be used for statistical correlation with conversion outcomes.

## Integration text
{integration_text}

## Instructions
Extract the following features precisely. Only include elements that are \
explicitly present in the text — do not infer or hallucinate.

## Response format
Return ONLY a valid JSON object with these exact fields:
{{
    "opening_pattern": {{
        "first_sentence": "<exact first sentence of the integration>",
        "opening_type": "<one of: personal_anecdote, direct_sponsor_mention, problem_statement, question, statistic, smooth_transition, abrupt_cut>",
        "opening_hook": "<the specific hook phrase used to start the ad, max 15 words>"
    }},
    "closing_pattern": {{
        "last_sentence": "<exact last sentence of the integration>",
        "closing_type": "<one of: cta_repeat, benefit_summary, urgency_push, casual_dismiss, back_to_content, emotional_close>",
        "closing_phrase": "<the specific closing phrase, max 15 words>"
    }},
    "transition": {{
        "transition_phrase": "<exact phrase used to bridge from regular content to ad, null if no clear transition>",
        "transition_style": "<one of: seamless, topic_related, abrupt, meta_acknowledgment, humor_bridge, none>",
        "acknowledges_sponsorship": <true if blogger explicitly says 'sponsor', 'sponsored', 'ad', 'partnered' etc.>
    }},
    "persuasion_phrases": [
        {{
            "phrase": "<exact phrase from text, max 20 words>",
            "function": "<one of: urgency, social_proof, benefit, pain_point, objection_handling, credibility, scarcity, fomo, empathy, authority>",
            "position": "<one of: opening, middle, closing>"
        }}
    ],
    "benefit_framings": [
        "<exact benefit statement as phrased by blogger, e.g. 'change your career in 7 months'>"
    ],
    "pain_point_framings": [
        "<exact pain point statement as phrased by blogger, e.g. 'stuck in a dead-end job'>"
    ],
    "cta_phrases": [
        {{
            "phrase": "<exact CTA wording>",
            "type": "<one of: link_click, promo_code, sign_up, consultation, download>",
            "urgency_words": ["<any urgency words in CTA: limited, now, today, hurry, etc.>"]
        }}
    ],
    "specificity_markers": [
        "<any specific claims: prices, timeframes, percentages, numbers — exact quotes>"
    ],
    "emotional_triggers": [
        "<phrases designed to trigger emotional response — exact quotes>"
    ],
    "rhetorical_questions": [
        "<any rhetorical questions used in the integration>"
    ]
}}

Return ONLY the JSON object, no additional text or markdown fencing."""
