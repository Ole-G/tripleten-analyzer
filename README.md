# TripleTen Ad Integration Analyzer

Automated pipeline that collects data about TripleTen's advertising integrations (YouTube, Instagram Reels, Stories, TikTok), fetches video metadata and transcripts, and prepares everything for LLM-powered correlation analysis with sales funnel data.

## What it does

1. **Reads** the master CSV with 134 ad integrations across 4 platforms
2. **Cleans** the data: converts Excel dates, fixes European number formatting, classifies URLs, removes duplicates
3. **Parses** YouTube videos via the YouTube Data API — fetches metadata (title, views, likes, duration, channel subscribers) and full transcripts with timestamps
4. **Outputs** structured JSON + a prepared CSV ready for LLM enrichment and correlation analysis

### Data breakdown (from the real dataset)

| Format | Total | Unique | Parseable |
|--------|-------|--------|-----------|
| YouTube | 62 | 56 | 56 |
| Instagram Reel | 42 | 37 | 37 |
| Story | 27 | 24 | 5 (Google Drive links) |
| TikTok | 3 | 3 | 3 |
| **Total** | **134** | **120** | **101** |

## Project structure

```
tripleten-analyzer/
├── config/
│   └── config.yaml                # Central configuration (paths, API settings, retry)
├── data/
│   ├── source/                    # Original CSV data
│   │   └── Tripleten_Test_Assignment2-Claude.csv
│   ├── raw/                       # Parser output (youtube_raw.json)
│   ├── enriched/                  # LLM-enriched data (future)
│   └── output/                    # Prepared CSV, final analysis
├── src/
│   ├── config_loader.py           # YAML + env var config loading
│   ├── parsers/
│   │   ├── base_parser.py         # Abstract base with retry logic
│   │   └── youtube_parser.py      # YouTube Data API + Transcript API
│   ├── enrichment/                # LLM enrichment (Phase 2)
│   │   ├── prompts.py            # Prompt templates for Claude
│   │   ├── extract_integration.py # Extract ad segment from transcript
│   │   └── analyze_content.py    # Analyze segment for content features
│   ├── analysis/                  # Correlation analysis (Phase 3-4)
│   │   ├── prompts.py            # Analysis prompt for Claude Opus
│   │   ├── merge_and_calculate.py # Merge data + calculate metrics
│   │   └── correlation_analysis.py # Send to Claude for analysis
│   ├── matching/                  # Sales data matching (future)
│   └── export/                    # Google Sheets export (future)
├── scripts/
│   ├── data_prep.py               # Phase 1: data preparation pipeline
│   ├── run_enrichment.py          # Phase 2: LLM enrichment pipeline
│   └── run_analysis.py            # Phase 3-4: correlation analysis
├── tests/
│   ├── test_parsers.py            # 46 unit tests (Phase 1)
│   ├── test_enrichment.py         # 22 unit tests (Phase 2)
│   └── test_analysis.py           # 22 unit tests (Phase 3-4)
├── requirements.txt
└── .env.example                   # API key template
```

## Prerequisites

- **Python 3.11+**
- **YouTube Data API key** (free, from [Google Cloud Console](https://console.cloud.google.com/apis/credentials))
- **Anthropic API key** (for Phase 2 enrichment and Phase 3-4 analysis — [Anthropic Console](https://console.anthropic.com/))

### Getting a YouTube Data API key

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or select an existing one)
3. Enable **YouTube Data API v3** in [API Library](https://console.cloud.google.com/apis/library/youtube.googleapis.com)
4. Go to **Credentials** > **Create Credentials** > **API Key**
5. Copy the key

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/Ole-G/tripleten-analyzer.git
cd tripleten-analyzer

# 2. Create and activate a virtual environment (recommended)
python -m venv venv
source venv/bin/activate        # Linux/macOS
# venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up API keys
cp .env.example .env
```

Edit `.env` and fill in your actual keys:

```env
YOUTUBE_API_KEY=your_youtube_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
```

## Usage

### Run the full data preparation pipeline

```bash
python -m scripts.data_prep
```

This will:
1. Read `data/source/Tripleten_Test_Assignment2-Claude.csv`
2. Validate, clean, and deduplicate the data (134 rows -> 120 unique)
3. Classify each URL by platform and parseability
4. Fetch YouTube video metadata and transcripts for all 56 YouTube URLs
5. Save outputs:
   - `data/output/prepared_integrations.csv` — cleaned dataset with added columns
   - `data/raw/youtube_raw.json` — full YouTube API response data + transcripts

### Use a custom input file

```bash
python -m scripts.data_prep --input path/to/your/file.csv
```

The CSV must be semicolon-separated (`;`) with at minimum these columns: `Date`, `Name`, `Format`, `Ad link`.

### Run tests

```bash
pytest tests/ -v
```

All 90 tests run without API keys (they test pure logic: URL extraction, date conversion, number parsing, URL classification, deduplication, LLM response parsing, metric calculations, etc.).

### Run LLM enrichment (Phase 2)

**Prerequisites**: Complete Phase 1 first (`python -m scripts.data_prep`), which generates `data/raw/youtube_raw.json`. You also need a valid `ANTHROPIC_API_KEY` in your `.env` file.

```bash
python -m scripts.run_enrichment
```

This will:
1. Read `data/raw/youtube_raw.json` (YouTube videos with transcripts)
2. For each video with a transcript:
   - **Extract** the ad integration segment using Claude (identifies the sponsored section from the full transcript)
   - **Analyze** the extracted segment for structured content features (offer type, CTA, tone, 8 quality scores, etc.)
3. Save outputs:
   - `data/enriched/youtube_enriched.json` — full enriched data (original + extraction + analysis)
   - `data/enriched/enrichment_summary.csv` — flat table for quick analysis in spreadsheets

**Resume support**: The script saves checkpoints every 10 records. If interrupted, just re-run the same command — already-processed videos will be skipped.

#### Use a custom input file

```bash
python -m scripts.run_enrichment --input path/to/your/youtube_raw.json
```

#### Enrichment output fields

Each video gets two enrichment steps:

**Extraction** — identifies the ad segment:
- `integration_text`, `integration_start_sec`, `integration_duration_sec`, `integration_position`, `is_full_video_ad`

**Analysis** — structured content features:
- Offer: `offer_type`, `offer_details`, `landing_type`
- CTA: `cta_type`, `cta_urgency`, `cta_text`
- Narrative: `has_personal_story`, `personal_story_type`, `pain_points_addressed`, `benefits_mentioned`
- Quality scores (1-10): `urgency`, `authenticity`, `storytelling`, `benefit_clarity`, `emotional_appeal`, `specificity`, `humor`, `professionalism`
- Meta: `overall_tone`, `language`, `product_positioning`, `target_audience_implied`, `social_proof`, `objection_handling`, `competitive_mention`, `price_mentioned`

### Run correlation analysis (Phase 3-4)

**Prerequisites**: Complete Phase 1 and Phase 2 first. You need a valid `ANTHROPIC_API_KEY` in your `.env` file.

```bash
python -m scripts.run_analysis
```

This will:
1. **Merge** all data sources — prepared CSV (120 integrations, full funnel) + YouTube enrichment (LLM analysis)
2. **Calculate** additional metrics — CPV, cost per purchase, funnel conversion rates, plan vs fact, engagement rate
3. **Send** the complete dataset to Claude Opus for deep correlation analysis
4. **Generate** `data/output/analysis_report.md` — the final analytical report

Outputs:
- `data/output/final_merged.csv` — complete merged table (~90 columns, all 120 integrations)
- `data/output/final_merged.json` — same data in JSON (sent to Claude)
- `data/output/analysis_report.md` — structured analytical report with recommendations

#### Options

```bash
# Skip merge if final_merged.json already exists
python -m scripts.run_analysis --skip-merge

# Use a different model (default: claude-opus-4-6)
python -m scripts.run_analysis --model claude-sonnet-4-5-20250929
```

**Note**: This step uses Claude Opus by default for deep analysis. Expected cost: ~$5-10 per run. Use `--model claude-sonnet-4-5-20250929` for a cheaper alternative.

#### Calculated metrics

| Metric | Formula |
|--------|---------|
| `cost_per_view` | Budget / Fact Reach |
| `cost_per_contact` | Budget / Contacts Fact |
| `cost_per_deal` | Budget / Deals Fact |
| `cost_per_purchase` | Budget / Purchase F - TOTAL |
| `traffic_to_contact_rate` | Contacts Fact / Traffic Fact |
| `contact_to_deal_rate` | Deals Fact / Contacts Fact |
| `full_funnel_conversion` | Purchase F - TOTAL / Fact Reach |
| `engagement_rate` | (likes + comments) / views (YouTube only) |
| `plan_vs_fact_reach` | Fact Reach / Reach Plan |

## Configuration

All settings are in `config/config.yaml`. Key options:

```yaml
youtube:
  transcript_languages: ["uk", "ru", "en"]   # Language fallback order
  batch_size: 50                              # IDs per API call (max 50)

retry:
  max_retries: 3                              # Retry attempts for failed requests
  backoff_base: 2                             # Exponential backoff base (seconds)

logging:
  level: "INFO"                               # Console log level
  file_level: "DEBUG"                         # File log level (logs/pipeline.log)
```

API keys are **never stored in config** — they are read from environment variables referenced in the YAML.

## Data pipeline details

### Input CSV format

The source CSV (`Tripleten_Test_Assignment2-Claude.csv`) has 52 columns with the full marketing funnel:

```
Reach → Traffic → Contacts → Deals → Calls → GTC → Purchases
```

Key columns used by the pipeline:

| Column | Description |
|--------|-------------|
| `Date` | Integration date (Excel serial number or date string) |
| `Name` | Blogger username |
| `Format` | Platform: youtube / reel / story / tiktok |
| `Ad link` | URL of the integration (parsed for video IDs) |
| `Budget` | Integration cost in USD |
| `Fact Reach` | Actual reach |
| `Contacts Fact` | Actual contacts generated |
| `Deals Fact` | Actual deals |
| `Purchase F - TOTAL` | Total purchases |

### Data transformations

| Transformation | Example |
|---------------|---------|
| Excel serial date → ISO | `45748` → `2025-04-01` |
| European decimal → float | `"2,6"` → `2.6` |
| YouTube URL → video ID | `youtu.be/uTc3U2Cqen4?t=331` → `uTc3U2Cqen4` |
| YouTube URL → timestamp | `?t=331` → `331` (seconds) |
| URL classification | Each URL gets `is_parseable`, `url_type`, `content_id` |
| Deduplication | By `(Name, Ad link)` — removes 14 duplicates |

### YouTube parser output

For each video, the parser fetches:

| Field | Source |
|-------|--------|
| `video_id`, `title`, `description` | YouTube Data API |
| `channel_name`, `channel_subscribers` | YouTube Data API |
| `view_count`, `like_count`, `comment_count` | YouTube Data API |
| `duration_seconds` | YouTube Data API |
| `publish_date`, `tags`, `thumbnail_url` | YouTube Data API |
| `transcript_full` (with timestamps) | YouTube Transcript API |
| `transcript_text` (plain text) | YouTube Transcript API |

Transcripts are fetched with language fallback: Ukrainian → Russian → English.

### Supported URL formats

| Platform | URL Pattern | Extracted ID |
|----------|------------|--------------|
| YouTube | `youtube.com/watch?v=ID` | 11-char video ID |
| YouTube | `youtu.be/ID` | 11-char video ID |
| YouTube | `youtube.com/live/ID` | 11-char video ID |
| YouTube | `youtube.com/shorts/ID` | 11-char video ID |
| Instagram | `instagram.com/reel/ID/` | Reel shortcode |
| TikTok | `tiktok.com/@user/video/ID` | Numeric video ID |

## Roadmap

- [x] **Phase 1**: Data preparation + YouTube parsing
- [x] **Phase 2**: LLM enrichment (extract integration text from transcripts, analyze tone/CTA/offer)
- [x] **Phase 3**: Sales funnel matching (merge data, calculate conversion metrics)
- [x] **Phase 4**: Correlation analysis via Claude Opus (find patterns between content and ROAS)
- [ ] **Phase 5**: Export to Google Sheets + report generation

## Troubleshooting

### "YouTube API key not found"

Make sure your `.env` file exists in the project root and contains `YOUTUBE_API_KEY=...`. The key must be a valid YouTube Data API v3 key with the API enabled in Google Cloud Console.

### "Transcripts are disabled for this video"

Some videos don't have subtitles/captions. The parser handles this gracefully — the video's metadata is still fetched, only the transcript fields will be empty. Check the `has_transcript` field in the output.

### Tests fail with "ModuleNotFoundError: cffi"

Install the missing dependency:

```bash
pip install cffi cryptography
```

### European number parsing issues

The source CSV uses commas as decimal separators (e.g., `"2,6"` = 2.6). This is handled automatically by the pipeline. If your CSV uses dots, it will work too.
