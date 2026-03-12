"""Prompt templates for LLM enrichment of ad integration transcripts."""

EXTRACT_INTEGRATION_PROMPT = """\
You are an analyst of influencer ad integrations for TripleTen.

You will receive a transcript with timestamps and an optional timestamp hint.
Your task is to extract the exact TripleTen-sponsored segment.

Input transcript:
{transcript_json}

Timestamp hint: {integration_timestamp}

Instructions:
1. Find the exact sponsored segment about TripleTen.
2. Use the timestamp hint as a clue, not as a hard boundary.
3. If the whole video is essentially an ad, mark it as a full-video ad.
4. Return only JSON.

JSON schema:
{{
  "integration_text": "full extracted ad segment",
  "integration_start_sec": 0,
  "integration_duration_sec": 0,
  "integration_position": "beginning|middle|end",
  "is_full_video_ad": false
}}
"""


ANALYZE_INTEGRATION_PROMPT = """\
You are an expert marketing analyst specializing in influencer ad integrations for TripleTen.

Analyze the ad integration text below. The goal is not only classification, but transparent classification.
Every important content judgment must be backed by short evidence quotes from the text.

Integration text:
{integration_text}

Allowed values:
- offer_type: discount, promo_code, free_consultation, free_trial, free_course, trial, bootcamp, career_change, other
- landing_type: programs_page, free_consultation, specific_course, website, landing_page, consultation_form, promo_page, app, other
- cta_type: link_in_description, promo_code, qr_code, swipe_up, direct_link, link_click, sign_up, consultation, download, other
- cta_urgency: none, low, medium, high
- personal_story_type: career_change, learning_experience, friend_recommendation, none
- social_proof: none, testimonial, statistics, celebrity
- overall_tone: enthusiastic, casual, professional, skeptical_converted, educational, conversational, humorous, inspirational, mixed
- product_positioning: career_change, upskill, side_income, tech_entry, general_education

Scoring rubric. Use the full 1-10 scale, but anchor your judgment to these examples:
- urgency: 1=no urgency, 3=soft encouragement, 5=one clear timely nudge, 7=explicit urgency or scarcity, 9=strong deadline/scarcity central to CTA
- authenticity: 1=generic ad copy, 3=lightly personalized, 5=some believable personal framing, 7=concrete personal experience or candid framing, 9=highly personal and difficult to fake
- storytelling: 1=no narrative, 3=minimal narrative, 5=simple before/after or mini-story, 7=clear narrative arc, 9=story is the backbone of persuasion
- benefit_clarity: 1=vague benefit, 3=benefits implied, 5=main benefit named, 7=multiple clear benefits, 9=benefits are concrete, specific, and easy to remember
- emotional_appeal: 1=emotionally flat, 3=light emotional language, 5=some aspiration or fear, 7=clear emotional framing, 9=emotion is a major driver of the pitch
- specificity: 1=generic claims, 3=one weak detail, 5=some specifics, 7=multiple concrete facts, 9=rich in precise numbers, timeframes, or concrete promises
- humor: 1=none, 3=lightly playful, 5=some intentional humor, 7=humor supports persuasion, 9=humor is memorable and central
- professionalism: 1=chaotic or sloppy, 3=rough but understandable, 5=acceptable structure, 7=well-structured and polished, 9=very polished and credible

Return only valid JSON with this schema:
{{
  "offer_type": "...",
  "offer_details": "...",
  "landing_type": "...",
  "cta_type": "...",
  "cta_urgency": "...",
  "cta_text": "exact CTA phrase",
  "has_personal_story": true,
  "personal_story_type": "...",
  "pain_points_addressed": ["..."],
  "benefits_mentioned": ["..."],
  "objection_handling": true,
  "social_proof": "...",
  "scores": {{
    "urgency": 1,
    "authenticity": 1,
    "storytelling": 1,
    "benefit_clarity": 1,
    "emotional_appeal": 1,
    "specificity": 1,
    "humor": 1,
    "professionalism": 1
  }},
  "score_details": {{
    "urgency": {{"score_band": "low|medium|high", "short_reason": "<=20 words", "evidence_quotes": ["quote 1", "quote 2"]}},
    "authenticity": {{"score_band": "low|medium|high", "short_reason": "<=20 words", "evidence_quotes": ["quote 1", "quote 2"]}},
    "storytelling": {{"score_band": "low|medium|high", "short_reason": "<=20 words", "evidence_quotes": ["quote 1", "quote 2"]}},
    "benefit_clarity": {{"score_band": "low|medium|high", "short_reason": "<=20 words", "evidence_quotes": ["quote 1", "quote 2"]}},
    "emotional_appeal": {{"score_band": "low|medium|high", "short_reason": "<=20 words", "evidence_quotes": ["quote 1", "quote 2"]}},
    "specificity": {{"score_band": "low|medium|high", "short_reason": "<=20 words", "evidence_quotes": ["quote 1", "quote 2"]}},
    "humor": {{"score_band": "low|medium|high", "short_reason": "<=20 words", "evidence_quotes": ["quote 1", "quote 2"]}},
    "professionalism": {{"score_band": "low|medium|high", "short_reason": "<=20 words", "evidence_quotes": ["quote 1", "quote 2"]}}
  }},
  "overall_tone": "...",
  "language": "uk|ru|en|other",
  "product_positioning": "...",
  "target_audience_implied": "...",
  "competitive_mention": false,
  "price_mentioned": false
}}
"""


TEXTUAL_ANALYSIS_PROMPT = """\
You are a linguistic analyst specializing in persuasion and advertising copy.

Analyze the following ad integration text from an influencer video promoting TripleTen.
Extract only features that are explicitly supported by the text. Do not invent evidence.

Integration text:
{integration_text}

Return only valid JSON with this schema:
{{
  "opening_pattern": {{
    "first_sentence": "exact first sentence",
    "opening_type": "personal_anecdote|direct_sponsor_mention|problem_statement|question|statistic|smooth_transition|abrupt_cut",
    "opening_hook": "short exact hook"
  }},
  "closing_pattern": {{
    "last_sentence": "exact last sentence",
    "closing_type": "cta_repeat|benefit_summary|urgency_push|casual_dismiss|back_to_content|emotional_close",
    "closing_phrase": "short exact closing phrase"
  }},
  "transition": {{
    "transition_phrase": "exact bridge phrase or null",
    "transition_style": "seamless|topic_related|abrupt|meta_acknowledgment|humor_bridge|none",
    "acknowledges_sponsorship": true
  }},
  "persuasion_phrases": [{{"phrase": "exact quote", "function": "urgency|social_proof|benefit|pain_point|objection_handling|credibility|scarcity|fomo|empathy|authority", "position": "opening|middle|closing"}}],
  "benefit_framings": ["exact quote"],
  "pain_point_framings": ["exact quote"],
  "cta_phrases": [{{"phrase": "exact quote", "type": "link_click|promo_code|sign_up|consultation|download", "urgency_words": ["..."]}}],
  "specificity_markers": ["exact quote"],
  "emotional_triggers": ["exact quote"],
  "rhetorical_questions": ["exact quote"]
}}
"""
