# Технічне завдання: Аналізатор ефективності рекламних інтеграцій TripleTen

## 1. Контекст проєкту

TripleTen — EdTech-платформа, яка залучає клієнтів через рекламні інтеграції у блогерів (YouTube, Instagram Reels, Stories, TikTok). Є внутрішня аналітика з повною воронкою (reach → traffic → contacts → deals → calls → GTC → purchases), але відсутній аналіз КОНТЕНТУ самих інтеграцій — що саме говориться у відео та як це корелює з конверсією.

**Мета:** Побудувати пайплайн, який автоматично збирає контент інтеграцій (транскрипти, метадані), збагачує їх LLM-аналізом і знаходить кореляції між характеристиками контенту та бізнес-результатами.

**Цільова аудиторія:** Маркетинг-команда TripleTen (цінують AI-рішення — вау-ефект від AI-інструментарію буде плюсом).

---

## 2. Вхідні дані: що вже є

### 2.1 Основне джерело: `Tripleten_Test_Assignment2-Claude.csv`

Файл є **єдиним джерелом правди** для всього пайплайну. Містить 134 записи рекламних інтеграцій із 52 колонками.

**Розбивка за форматами:**

| Формат | К-сть | Парсабельних URL | Примітка |
|--------|-------|------------------|----------|
| YouTube | 62 | 62 | Усі мають URL, транскрипти через YouTube Transcript API |
| Instagram Reel | 42 | 41 | 1 без URL. Транскрипти через Whisper |
| Story | 27 | 5 | 22 — локальні файли (.mov/.mp4), парсинг обмежений |
| TikTok | 3 | 3 | URL є, транскрипти через Whisper |

**Ключові колонки (згруповано за призначенням):**

```
ІДЕНТИФІКАЦІЯ:
  [0]  Date                — дата інтеграції (Excel serial number)
  [1]  Name                — нік блогера (ключ для зв'язку)
  [2]  Profile link         — посилання на профіль блогера
  [3]  Topic               — тематична ніша (Career, Tech, Finance, Gaming тощо — 22 ніші)
  [4]  Manager             — менеджер TripleTen
  [5]  Format              — формат: youtube / reel / story / tiktok
  [6]  Ad link             — ⭐ ПОСИЛАННЯ НА ІНТЕГРАЦІЮ (джерело URL для парсера)
  [7]  UTM Link            — UTM-посилання для трекінгу
  [8]  UTM Campaign        — назва UTM-кампанії

БЮДЖЕТ І ОХОПЛЕННЯ:
  [9]  Budget              — бюджет, USD ($250–$23,000; загалом ~$563K)
  [10] Reach (Plan)        — плановий охоплення
  [11] Fact Reach          — фактичне охоплення
  [12] Median %            — медіана % від підписників
  [13] CPM (Plan)          — план CPM
  [14] CPM Fact            — факт CPM

ТРАФІК:
  [15] CTR Plan / [16] CTR Fact
  [17] Traffic Plan / [18] Traffic Fact
  [19] CPC Plan / [20] CPC Fact

КОНВЕРСІЇ (ПОВНА ВОРОНКА):
  [21] CR0 Plan / [22] CR0 Fact       — конверсія трафік → контакт
  [23] Contacts Plan / [24] Contacts Fact
  [25] CPContact Plan / [26] CPContact Fact
  [27-28] CR1 Contact → Deal (Plan/Fact)
  [29] Deals Plan / [30] Deals Fact
  [31-32] CR3 Deal → Call (Plan/Fact)
  [33] Calls Plan / [34] Calls Fact
  [35] CR4 Call → GTC Fact
  [36] GTC Plan / [37] GTC Fact

ПОКУПКИ (КОГОРТНИЙ АНАЛІЗ):
  [38-39] CR Call → Purchase (Plan/Fact, 1 month)
  [40] Purchase F - TOTAL              — ⭐ загальні покупки (ключова метрика)
  [41] CMC F - TOTAL                   — загальний CMC
  [42] Purchase P - 1 month / [43] Purchase F - 1 month
  [44] CMC P - 1 month / [45] CMC F - 1 month
  [46-51] Purchase/CMC за 2, 3, 6 місяців
```

### 2.2 Статистика даних

- **26 із 134 записів** мають хоча б одну покупку (Purchase F - TOTAL > 0)
- **14 дуплікатів** (той самий блогер + те саме Ad link, ймовірно різні рядки воронки або формати)
- **20 записів** без парсабельних URL (локальні файли типу `blogger.mov`)
- **22 тематичні ніші**: Career, Finance, Tech, Gaming, Knowledge, Mental Health, Lifestyle, Movies, Sketchers, Self Development, Parents, Teacher, Interview, Hobby, AI, Science, History, Auto, Travel, Coding, GameDev
- **Бюджетний діапазон:** $250–$23,000

### 2.3 Що потрібно ДОДАТИ до наявних даних

Наявний CSV містить ВСЮ воронку, але **нічого про сам контент інтеграції**. Парсер повинен додати:

1. **Транскрипт відео / тексти рілсів** — що саме говорить блогер
2. **Текст саме рекламного блоку** — витягнутий LLM із повного транскрипту
3. **Якісні характеристики контенту** — тон, оффер, CTA, наративна структура тощо
4. **Додаткові метрики відео** — лайки, коментарі (YouTube API дає більше, ніж є в CSV)

---

## 3. Архітектура пайплайну

```
Tripleten_Test_Assignment2-Claude.csv
          │
          ▼
┌─────────────────────────────────┐
│  КРОК 1: ПІДГОТОВКА ДАНИХ       │
│  • Parse CSV                    │
│  • Конвертація дат              │
│  • Дедуплікація                 │
│  • Класифікація за парсабельністю│
│  • Витяг video_id з Ad link     │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  КРОК 2: ПАРСИНГ КОНТЕНТУ       │
│                                 │
│  YouTube (62 URL):              │
│  ├─ YouTube Data API → метадані │
│  └─ youtube-transcript-api      │
│     → транскрипти з таймкодами  │
│                                 │
│  Instagram Reels (41 URL):      │
│  ├─ Apify → метадані + відео    │
│  └─ Whisper API → транскрипти   │
│                                 │
│  TikTok (3 URL):                │
│  ├─ Apify → метадані + відео    │
│  └─ Whisper API → транскрипти   │
│                                 │
│  Stories / без URL (22+20):     │
│  └─ Пропускаємо або manual input│
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  КРОК 3: LLM-ЗБАГАЧЕННЯ         │
│                                 │
│  Для кожного транскрипту:       │
│  ├─ Виділення рекламного блоку  │
│  ├─ Класифікація оферу і CTA   │
│  ├─ Оцінка тону та емоцій      │
│  ├─ Аналіз наративної структури │
│  └─ Екстракція ключових аргумен.│
│                                 │
│  Claude API (claude-sonnet-4-5) │
│  Batch processing + retry logic │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  КРОК 4: ЗВЕДЕННЯ + АНАЛІЗ      │
│                                 │
│  • Merge: CSV воронка + контент │
│  • Розрахунок додаткових метрик │
│  • Export → Google Sheets       │
│  • Завантаження в Claude Opus   │
│    (до 1M токенів контексту)    │
│  • Кореляційний аналіз          │
│  • Генерація звіту              │
└─────────────────────────────────┘
```

---

## 4. Детальна специфікація кроків

### 4.1 Крок 1: Підготовка даних (`src/data_prep.py`)

```python
# Вхід: Tripleten_Test_Assignment2-Claude.csv
# Вихід: data/prepared/integrations_prepared.json

Логіка:
1. Прочитати CSV (separator=';', encoding='utf-8')
2. Нормалізувати назви колонок (прибрати \n, trim, snake_case)
3. Конвертувати Date з Excel serial → ISO date
4. Конвертувати числові поля (Budget, Reach, Traffic тощо) → float/int
5. Для кожного рядка визначити:
   - platform: 'youtube' | 'instagram_reel' | 'instagram_story' | 'tiktok'
   - is_parseable: True якщо Ad link — валідний URL
   - video_id: витягнути з URL
     • YouTube: regex для youtu.be/{id} або watch?v={id}
     • Instagram: regex для /reel/{id}/
     • TikTok: regex для /video/{id}
   - integration_timestamp: якщо URL містить ?t=NNN → початок інтеграції у відео
6. Дедуплікація: якщо (Name + Ad link) повторюється — залишити рядок з
   більш повними даними, або merged row
7. Зберегти JSON з усіма полями + новими
```

**Обробка дат:**
```python
from datetime import datetime, timedelta

def excel_serial_to_date(serial):
    """Excel serial number → ISO date string"""
    return (datetime(1899, 12, 30) + timedelta(days=int(serial))).strftime('%Y-%m-%d')
# Приклад: 45748 → '2025-04-08'
```

**Витяг video_id з Ad link:**
```python
import re

def extract_video_id(url, platform):
    if platform == 'youtube':
        # youtu.be/VIDEO_ID або watch?v=VIDEO_ID
        match = re.search(r'(?:youtu\.be/|watch\?v=)([a-zA-Z0-9_-]{11})', url)
        return match.group(1) if match else None
    elif platform == 'instagram_reel':
        # /reel/REEL_ID/
        match = re.search(r'/reel/([A-Za-z0-9_-]+)', url)
        return match.group(1) if match else None
    elif platform == 'tiktok':
        # /video/VIDEO_ID
        match = re.search(r'/video/(\d+)', url)
        return match.group(1) if match else None
```

### 4.2 Крок 2: Парсинг контенту

#### 4.2.1 YouTube Parser (`src/parsers/youtube_parser.py`)

```python
# Вхід: список video_id з prepared data
# Вихід: data/raw/youtube_content.json

Для кожного video_id:

A) YouTube Data API (потрібен API key):
   - snippet: title, description, tags, channelTitle, publishedAt, thumbnails
   - statistics: viewCount, likeCount, commentCount
   - contentDetails: duration

B) youtube-transcript-api (без ключа):
   - Спробувати мови: ['en', 'en-US', 'uk', 'ru'] + auto-generated
   - Зберегти з таймкодами: [{text, start, duration}, ...]
   - Якщо транскрипту немає → позначити для Whisper fallback

C) Timestamp інтеграції:
   - Якщо Ad link містить ?t=NNN → це початок інтеграції
   - Витягти фрагмент транскрипту від t до t+120сек (типова інтеграція)

Обробка помилок:
   - Video unavailable → skip, log
   - No transcript → flag for manual/Whisper
   - Rate limit → exponential backoff
   - Quota exceeded → зберегти прогрес, продовжити потім
```

**Важливо:** URL у CSV вже містять `?t=NNN` — таймкод початку інтеграції у відео! Це дуже цінно для точного виділення рекламного блоку з транскрипту.

```python
def extract_integration_timestamp(url):
    """Витягти ?t=seconds з YouTube URL"""
    match = re.search(r'[?&]t=(\d+)', url)
    return int(match.group(1)) if match else None

# Приклад: https://youtu.be/uTc3U2Cqen4?t=331 → 331 секунд
```

#### 4.2.2 Instagram Reels Parser (`src/parsers/reels_parser.py`)

```python
# Вхід: список Reel URL з prepared data
# Вихід: data/raw/reels_content.json

Варіант A — Apify (рекомендований):
   Actor: apify/instagram-scraper
   - caption, likesCount, commentsCount, timestamp
   - videoUrl → скачати → Whisper → транскрипт

Варіант B — instaloader (Python, безкоштовний):
   pip install instaloader
   - Потрібен Instagram login
   - Скачує відео + метадані
   - Далі Whisper для транскрипту

Транскрибування:
   - OpenAI Whisper API ($0.006/min) — найпростіше
   - Або локальний faster-whisper (безкоштовно, потребує GPU)
```

#### 4.2.3 TikTok Parser (`src/parsers/tiktok_parser.py`)

Аналогічно Instagram: Apify actor або yt-dlp для скачування → Whisper.

Лише 3 відео — можна обробити напів-вручну.

#### 4.2.4 Stories та файли без URL

**22 stories без URL + 20 записів з локальними файлами (.mov/.mp4)** — парсинг неможливий автоматично. Опції:

1. **Ігнорувати** для контент-аналізу (залишити тільки воронку з CSV)
2. **Manual upload** — якщо є доступ до файлів, завантажити → Whisper
3. **Окрема категорія** — аналізувати як групу без контенту

**Рекомендація:** Сфокусуватися на 62 YouTube + 41 Reels + 3 TikTok = **106 парсабельних інтеграцій** (79% від загальної кількості).

### 4.3 Крок 3: LLM-збагачення (`src/enrichment/`)

#### 4.3.1 Виділення рекламного блоку (`enrichment/extract_integration.py`)

Для YouTube-відео з таймкодом:
```python
def get_integration_segment(transcript_segments, start_time, window=120):
    """Вирізати сегмент транскрипту навколо рекламної інтеграції"""
    return [seg for seg in transcript_segments
            if seg['start'] >= start_time and seg['start'] <= start_time + window]
```

Для відео без таймкоду або Reels (де вся інтеграція = все відео):

**Промпт для Claude (`enrichment/prompts.py`):**

```python
EXTRACT_INTEGRATION_PROMPT = """
Тобі надано повний транскрипт відео. Знайди рекламну інтеграцію (спонсорський блок,
де блогер рекламує TripleTen / освітню платформу) і поверни JSON:

{
  "integration_text": "дослівний текст рекламного блоку",
  "integration_start_sec": <приблизний таймкод початку>,
  "integration_duration_sec": <тривалість>,
  "integration_position": "beginning | middle | end",
  "is_full_video_ad": <true якщо все відео — одна інтеграція (типово для Reels)>
}

Якщо рекламний блок не знайдено, поверни {"integration_text": null, "reason": "..."}
"""
```

#### 4.3.2 Аналіз характеристик контенту (`enrichment/analyze_content.py`)

**Промпт для збагачення кожної інтеграції:**

```python
ANALYZE_INTEGRATION_PROMPT = """
Проаналізуй текст рекламної інтеграції TripleTen і поверни JSON:

{
  // ОФФЕР
  "offer_type": "discount | promo_code | free_consultation | free_trial | free_course | other",
  "offer_details": "конкретні деталі оферу",
  "landing_type": "programs_page | free_consultation | specific_course",

  // CTA
  "cta_type": "link_in_description | promo_code | qr_code | swipe_up | direct_link",
  "cta_urgency": "none | low | medium | high",
  "cta_text": "дослівний текст CTA",

  // НАРАТИВНА СТРУКТУРА
  "has_personal_story": true/false,
  "personal_story_type": "career_change | learning_experience | friend_recommendation | none",
  "pain_points_addressed": ["список болів аудиторії, які зачіпаються"],
  "benefits_mentioned": ["список вигод, що озвучуються"],
  "objection_handling": true/false,
  "social_proof": "none | testimonial | statistics | celebrity",

  // ЕМОЦІЙНІ ХАРАКТЕРИСТИКИ (шкала 1-10)
  "scores": {
    "urgency": <1-10>,
    "authenticity": <1-10>,
    "storytelling": <1-10>,
    "benefit_clarity": <1-10>,
    "emotional_appeal": <1-10>,
    "specificity": <1-10>,
    "humor": <1-10>,
    "professionalism": <1-10>
  },

  // МОВА ТА ТОН
  "overall_tone": "enthusiastic | casual | professional | skeptical_converted | educational",
  "language": "en | es | other",
  "speaking_speed": "slow | moderate | fast",

  // ПРОДУКТОВЕ ПОЗИЦІОНУВАННЯ
  "product_positioning": "career_change | upskill | side_income | tech_entry | general_education",
  "target_audience_implied": "опис цільової аудиторії",
  "competitive_mention": true/false,
  "price_mentioned": true/false
}

Відповідай ТІЛЬКИ JSON, без пояснень.
"""
```

**Технічні деталі batch-обробки:**

```python
# Використовувати Claude Sonnet 4.5 для збагачення (швидший, дешевший)
# ~106 інтеграцій × ~2000 токенів на запит = ~212K токенів input
# Вартість: ~$0.60-1.20

import anthropic
import asyncio
import json

client = anthropic.Anthropic()

async def enrich_batch(integrations, batch_size=10):
    results = []
    for i in range(0, len(integrations), batch_size):
        batch = integrations[i:i+batch_size]
        tasks = [enrich_single(item) for item in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        results.extend(batch_results)
        # Rate limit: max 50 req/min for Sonnet
        await asyncio.sleep(2)
    return results

async def enrich_single(integration):
    for attempt in range(3):  # retry logic
        try:
            response = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": f"{ANALYZE_INTEGRATION_PROMPT}\n\nТекст інтеграції:\n{integration['integration_text']}"
                }]
            )
            return json.loads(response.content[0].text)
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
            else:
                return {"error": str(e)}
```

### 4.4 Крок 4: Зведення та аналіз

#### 4.4.1 Merge та розрахунок метрик (`src/analysis/merge_and_calculate.py`)

```python
# Злити CSV-дані (воронка) + парсений контент + LLM-збагачення
# Ключ злиття: video_id або (Name + Ad link)

# Додаткові розрахункові метрики:
calculated_metrics = {
    "cost_per_view": budget / fact_reach,
    "cost_per_contact": budget / contacts_fact,
    "cost_per_deal": budget / deals_fact,
    "cost_per_purchase": budget / purchase_total,  # якщо > 0
    "traffic_to_contact_rate": contacts_fact / traffic_fact,
    "contact_to_deal_rate": deals_fact / contacts_fact,
    "deal_to_purchase_rate": purchase_total / deals_fact,
    "full_funnel_conversion": purchase_total / fact_reach,
    "revenue_efficiency": purchase_total * avg_ltv / budget,  # ROAS proxy
    "engagement_rate_youtube": (likes + comments) / views,  # для YouTube
    "plan_vs_fact_reach": fact_reach / reach_plan,  # перевиконання/недовиконання
    "plan_vs_fact_traffic": traffic_fact / traffic_plan,
}
```

#### 4.4.2 Кореляційний аналіз (`src/analysis/correlation_analysis.py`)

**Завантажити ВСЕ в Claude Opus 4.6 (контекст до 1M токенів):**

```python
# Формат подачі: JSON із усіма записами
# Оцінка розміру: 106 записів × ~3000 токенів = ~320K токенів — вміщується легко

CORRELATION_PROMPT = """
Тобі надано повний датасет рекламних інтеграцій TripleTen (JSON).

Кожен запис містить:
- ВОРОНКУ: reach → traffic → contacts → deals → calls → GTC → purchases (plan + fact)
- БЮДЖЕТ: витрати на інтеграцію
- КОНТЕНТ: повний транскрипт інтеграції + LLM-аналіз (тон, оффер, CTA, scores)
- МЕТАДАНІ: платформа, ніша блогера, формат, дата

АНАЛІЗ:

1. КОРЕЛЯЦІЇ КОНТЕНТ → ПОКУПКИ
   Із 134 інтеграцій лише 26 мають покупки > 0. Що спільного у цих 26?
   - Які LLM-scores (urgency, authenticity, storytelling тощо) найвищі?
   - Який offer_type домінує серед інтеграцій з покупками?
   - Чи є залежність від overall_tone?
   - Чи наявність personal_story корелює з конверсією?
   - Яка integration_position (beginning/middle/end) найефективніша?

2. ВОРОНКА: ДЕ ВТРАЧАЮТЬСЯ ГРОШІ?
   - Де найбільший drop-off у воронці (traffic→contacts vs contacts→deals vs deals→purchase)?
   - Чи залежить bottleneck від типу контенту?
   - Порівняй план vs факт: які інтеграції перевиконали, які недовиконали? Що в контенті різне?

3. ПЛАТФОРМИ ТА ФОРМАТИ
   - YouTube (62) vs Reels (42) vs Stories (27) vs TikTok (3): де найкращий ROI?
   - Чи є різниця в конверсії залежно від формату при однаковому бюджеті?

4. ТЕМАТИЧНІ НІШІ
   22 ніші (Career, Finance, Tech, Gaming тощо):
   - ТОП-5 ніш за конверсією
   - ТОП-5 ніш за ROI (purchases/budget)
   - Які ніші переоцінені (високий бюджет, мало результату)?

5. БЮДЖЕТНА ЕФЕКТИВНІСТЬ
   Діапазон $250–$23,000:
   - Чи є sweet spot бюджету?
   - Мікро-інфлюенсери ($250-2000) vs макро ($10,000+): де кращий ROI?
   - Які "темні конячки" — малий бюджет, високий результат?

6. ПАТЕРНИ УСПІХУ ТА ПРОВАЛУ
   - ТОП-5 спільних рис інтеграцій з покупками
   - ТОП-5 спільних рис інтеграцій з нульовими покупками при високому бюджеті
   - Текстове порівняння: в чому КОНКРЕТНА різниця сценаріїв?
   - Найефективніші формулювання, CTA, офери

7. АНОМАЛІЇ
   - Великий reach але 0 traffic — чому?
   - Багато contacts але 0 deals — проблема оферу чи таргету?
   - Хтось отримав purchases при мінімальному бюджеті — що це за кейс?

8. РЕКОМЕНДАЦІЇ
   На основі даних сформулюй:
   a) Ідеальний бриф для блогера (що має бути в сценарії)
   b) Чеклист DO / DON'T для нових інтеграцій
   c) Рекомендований бюджетний split за платформами і нішами
   d) 3 конкретні гіпотези для A/B-тестування в наступних кампаніях

Відповідай з конкретними прикладами з даних (назви блогерів, числа).
Де можливо — порівнюй групи і давай статистику.
"""
```

---

## 5. Структура проєкту

```
tripleten-integration-analyzer/
├── README.md
├── requirements.txt
├── .env.example                      # API keys template
├── config.yaml                       # Налаштування пайплайну
│
├── data/
│   ├── source/
│   │   └── Tripleten_Test_Assignment2-Claude.csv   # ⭐ ВХІДНИЙ ФАЙЛ
│   ├── prepared/
│   │   └── integrations_prepared.json              # Після Кроку 1
│   ├── raw/
│   │   ├── youtube_content.json                    # YouTube метадані + транскрипти
│   │   ├── reels_content.json                      # Reels метадані + транскрипти
│   │   └── tiktok_content.json                     # TikTok контент
│   ├── enriched/
│   │   └── integrations_enriched.json              # Після LLM-збагачення
│   └── output/
│       ├── final_merged.json                       # Зведені дані
│       ├── final_merged.csv                        # Для Google Sheets
│       └── analysis_report.md                      # Звіт
│
├── src/
│   ├── __init__.py
│   ├── data_prep.py                  # Крок 1: парсинг CSV, нормалізація
│   ├── parsers/
│   │   ├── __init__.py
│   │   ├── youtube_parser.py         # YouTube Data API + Transcript API
│   │   ├── reels_parser.py           # Instagram Reels (Apify + Whisper)
│   │   └── tiktok_parser.py          # TikTok (Apify + Whisper)
│   ├── enrichment/
│   │   ├── __init__.py
│   │   ├── prompts.py                # Усі промпти для LLM
│   │   ├── extract_integration.py    # Виділення рекламного блоку
│   │   └── analyze_content.py        # Класифікація + scores
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── merge_and_calculate.py    # Злиття + додаткові метрики
│   │   └── correlation_analysis.py   # Аналіз через Claude Opus
│   └── export/
│       ├── __init__.py
│       ├── sheets_exporter.py        # Google Sheets export
│       └── report_generator.py       # Markdown звіт
│
├── scripts/
│   ├── run_pipeline.py               # ⭐ Повний пайплайн одною командою
│   ├── run_step.py                   # Окремі кроки (--step 1/2/3/4)
│   └── check_data_quality.py         # Перевірка якості даних
│
└── tests/
    ├── test_data_prep.py
    ├── test_youtube_parser.py
    └── test_enrichment.py
```

---

## 6. Порядок виконання в Claude Code

### Етап 1: Ініціалізація (5 хв)
```bash
mkdir -p tripleten-integration-analyzer/{data/{source,prepared,raw,enriched,output},src/{parsers,enrichment,analysis,export},scripts,tests}
cd tripleten-integration-analyzer

# Скопіювати CSV
cp /path/to/Tripleten_Test_Assignment2-Claude.csv data/source/

# Залежності
cat > requirements.txt << 'EOF'
google-api-python-client>=2.0
youtube-transcript-api>=0.6
anthropic>=0.40
pandas>=2.0
gspread>=6.0
oauth2client>=4.1
python-dotenv>=1.0
apify-client>=1.0
openai>=1.0            # для Whisper API
aiohttp>=3.9
EOF

pip install -r requirements.txt
```

### Етап 2: data_prep.py (~30 хв розробки)
- Парсинг CSV, нормалізація 52 колонок
- Витяг video_id + integration_timestamp з Ad link
- Класифікація кожного запису за парсабельністю
- Дедуплікація з логом
- Вихід: `data/prepared/integrations_prepared.json`
- **Тест:** перевірити що 62 YouTube мають video_id, 41 Reel мають reel_id

### Етап 3: youtube_parser.py (~1 год розробки)
- Batch-запити до YouTube Data API (62 відео = 62 units, далеко від ліміту 10K)
- Транскрипти через youtube-transcript-api
- Для відео з `?t=NNN` — автоматичне виділення сегменту інтеграції
- Fallback: позначити відео без транскрипту
- **Тест:** 3-5 відео, перевірити що транскрипт + метадані повертаються

### Етап 4: reels_parser.py (~1 год розробки)
- Apify client для метаданих Reels
- Скачування відео → Whisper API для транскрипту
- Для Reels транскрипт = весь рекламний блок (рідко що ще)
- **Тест:** 2-3 рілси

### Етап 5: enrichment (~1 год розробки)
- `extract_integration.py` — для YouTube виділення рекламного блоку з повного транскрипту (використовуючи timestamp)
- `analyze_content.py` — batch через Claude Sonnet 4.5
- Retry + rate limit handling
- Зберігання проміжних результатів (resume на випадок збою)
- **Тест:** 5 інтеграцій, перевірити JSON output

### Етап 6: merge + analysis (~1 год розробки)
- `merge_and_calculate.py` — злиття всіх джерел, розрахунок метрик
- `correlation_analysis.py` — завантаження в Claude Opus 4.6
- Export у Google Sheets + Markdown звіт
- **Тест:** повний прогін на всіх даних

### Етап 7: run_pipeline.py (~30 хв)
- Об'єднати все в послідовний пайплайн
- CLI з аргументами: `--step`, `--skip-parsed`, `--dry-run`
- Логування прогресу

---

## 7. Необхідні API ключі та доступи

| Ресурс | Як отримати | Вартість |
|--------|-------------|----------|
| YouTube Data API v3 | Google Cloud Console → APIs & Services | Безкоштовно (10K units/день) |
| Anthropic API | console.anthropic.com | ~$2-5 за весь аналіз |
| OpenAI Whisper API | platform.openai.com | ~$0.50 (44 відео × ~1хв) |
| Apify | apify.com | Free tier 30с compute/міс або ~$5 |
| Google Sheets API | Google Cloud Console | Безкоштовно |

**`.env` файл:**
```
YOUTUBE_API_KEY=your_key
ANTHROPIC_API_KEY=your_key
OPENAI_API_KEY=your_key          # для Whisper
APIFY_API_TOKEN=your_token
GOOGLE_SHEETS_CREDENTIALS=path/to/credentials.json
```

---

## 8. Очікуваний результат

### 8.1 Зведена таблиця (Google Sheets)
134 рядки з ~80 колонками: оригінальна воронка (52 кол.) + парсений контент (~10 кол.) + LLM-аналіз (~18 кол.) + розрахункові метрики (~10 кол.)

### 8.2 Аналітичний звіт (Markdown, 15-20 стор.)
- Executive summary з ключовими знахідками
- Кореляції контент ↔ конверсія (з числами і прикладами)
- Порівняння платформ і ніш
- Воронкові bottlenecks
- Конкретні рекомендації

### 8.3 Guidelines для інтеграцій
- Шаблон ідеального сценарію інтеграції
- DO / DON'T чеклист
- Рекомендований бюджетний split

### 8.4 Вау-ефект
- Весь аналіз запускається однією командою: `python scripts/run_pipeline.py`
- AI аналізує ТЕКСТ інтеграцій і знаходить те, що не видно з цифр
- Конкретні приклади: "блогер X сказав Y — і це дало Z конверсій, а блогер A сказав B — і це дало 0"

---

## 9. Технічні примітки

- **YouTube Transcript API** — безкоштовний, не потребує ключа. Але не всі відео мають субтитри. Fallback: Whisper на скачаному аудіо через yt-dlp.
- **Таймкоди в URL** — 52 з 62 YouTube URL мають `?t=NNN`. Це gold — точний початок інтеграції, не потрібно шукати в транскрипті.
- **Дедуплікація** — 14 рядків дублюються (Name + Ad link). Потрібно з'ясувати: це Stories + Reel одного блогера, чи помилка в даних.
- **Purchase F - TOTAL** — лише 26 записів >0. Для кореляційного аналізу це мало, тому варто також аналізувати проміжні етапи воронки (contacts, deals).
- **Загальний бюджет $563K** — збігається з цифрою з Notion-аналізу (не з Excel, де $497K — потрібно верифікувати розбіжність).
- **Claude Opus 4.6** — до 1M токенів контексту. 134 записи з усіма даними ≈ 300-400K токенів — вміщується з запасом.
