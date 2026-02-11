# Технічне завдання: Аналізатор ефективності рекламних інтеграцій TripleTen

## Контекст проєкту

TripleTen — EdTech-платформа, яка активно використовує рекламні інтеграції у YouTube-блогерів та Instagram Reels для залучення клієнтів. Існує аналітичний бриф з даними про інтеграції та продажі, але аналіз наразі виконується вручну, а кореляції між контентом відео та конверсіями залишаються невідомими.

**Мета:** Побудувати автоматизований пайплайн, який збирає дані про рекламні інтеграції (транскрипти, метадані, метрики), зіставляє їх з даними продажів і за допомогою LLM знаходить приховані патерни, що впливають на конверсію.

**Цільова аудиторія результату:** Маркетинг-команда TripleTen (люблять AI-рішення — "вау-ефект" від AI-інструментарію буде плюсом при презентації).

---

## Архітектура рішення

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  DATA SOURCES   │    │   PROCESSING     │    │    ANALYSIS     │
│                 │    │                  │    │                 │
│ YouTube API/    │───▶│ Парсер метаданих │───▶│ Google Sheets   │
│ Apify scraper   │    │ + транскриптів   │    │ (зведена табл.) │
│                 │    │                  │    │                 │
│ Instagram/Reels │───▶│ Нормалізація     │───▶│ Claude Opus 4.6 │
│ (Apify)         │    │ даних            │    │ (кореляційний   │
│                 │    │                  │    │  аналіз)        │
│ Дані продажів   │───▶│ Матчинг з        │───▶│                 │
│ (Excel/CSV)     │    │ продажами        │    │ Звіт + рекомен- │
│                 │    │                  │    │ дації            │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

---

## Фаза 1: Парсер даних інтеграцій

### 1.1 YouTube Parser

**Вхідні дані:** Список URL відео з рекламними інтеграціями (із брифу/Excel).

**Що збирати для кожного відео:**

| Поле | Джерело | Примітка |
|------|---------|----------|
| `video_id` | URL | Унікальний ідентифікатор |
| `title` | YouTube Data API / парсинг | Назва відео |
| `description` | YouTube Data API / парсинг | Опис відео |
| `channel_name` | YouTube Data API | Назва каналу |
| `channel_subscribers` | YouTube Data API | К-сть підписників на момент парсингу |
| `publish_date` | YouTube Data API | Дата публікації |
| `view_count` | YouTube Data API | К-сть переглядів |
| `like_count` | YouTube Data API | К-сть лайків |
| `comment_count` | YouTube Data API | К-сть коментарів |
| `duration` | YouTube Data API | Тривалість відео |
| `tags` | YouTube Data API | Теги відео |
| `transcript_full` | YouTube Transcript API | Повний транскрипт з таймкодами |
| `integration_text` | LLM-екстракція | Текст саме рекламної інтеграції (виділений із транскрипту) |
| `thumbnail_url` | YouTube Data API | URL мініатюри |

**Технічна реалізація:**

```bash
# Варіант A: YouTube Data API + youtube-transcript-api (Python)
pip install google-api-python-client youtube-transcript-api

# Варіант B: Apify Actor (no-code/low-code)
# Actor: apify/youtube-scraper — парсить метадані
# Actor: bernardo/youtube-transcript-scraper — парсить транскрипти
```

**Рекомендований підхід — Python-скрипт:**

```python
# Псевдокод основної логіки
for video_url in video_urls_from_brief:
    metadata = youtube_api.get_video_details(video_url)
    transcript = youtube_transcript_api.get_transcript(video_id, languages=['uk', 'ru', 'en'])
    
    # Зберегти в структурований формат
    row = {**metadata, 'transcript': transcript}
    results.append(row)

# Експорт у CSV/Google Sheets
export_to_sheets(results)
```

### 1.2 Instagram Reels Parser

**Підхід:** Apify Actor (`apify/instagram-reel-scraper` або `apify/instagram-scraper`).

**Що збирати:**

| Поле | Примітка |
|------|----------|
| `reel_url` | Посилання |
| `author` | Нік блогера |
| `caption` | Текст підпису |
| `view_count` | Перегляди |
| `like_count` | Лайки |
| `comment_count` | Коментарі |
| `publish_date` | Дата публікації |
| `audio_transcript` | Транскрибувати через Whisper, якщо потрібно |

**Примітка:** Instagram не віддає транскрипти нативно. Якщо потрібен текст з Reels — завантажити аудіодоріжку та прогнати через Whisper API.

### 1.3 Файл із переліком інтеграцій

Створити вхідний файл `integrations_list.csv`:

```csv
platform,url,blogger_name,integration_date,campaign_name,cost_usd
youtube,https://youtube.com/watch?v=XXXXX,BloggerName,2025-01-15,Campaign_Q1,5000
instagram,https://instagram.com/reel/XXXXX,BloggerName2,2025-01-20,Campaign_Q1,2000
```

---

## Фаза 2: LLM-збагачення даних

### 2.1 Виділення тексту інтеграції з транскрипту

Транскрипт містить все відео, а інтеграція — лише фрагмент. Потрібно виділити саме рекламний блок.

**Промпт для Claude / GPT (через Google Sheets extension або API):**

```
Ти — аналітик рекламних інтеграцій. Тобі надано повний транскрипт YouTube-відео.

Знайди в транскрипті рекламну інтеграцію (спонсорський блок) та поверни:
1. integration_text — дослівний текст рекламної інтеграції
2. integration_start_time — приблизний таймкод початку
3. integration_duration_sec — тривалість інтеграції в секундах
4. offer_type — тип оферу (знижка, промокод, безкоштовний курс, тріал тощо)
5. offer_details — конкретні деталі оферу (промокод, % знижки тощо)
6. cta_type — тип call-to-action (посилання в описі, промокод, QR-код тощо)
7. tone — загальний тон інтеграції (позитивний, нейтральний, нативний, агресивний)
8. personal_story — чи є особистий досвід блогера (так/ні)
9. pain_points — які болі аудиторії зачіпаються
10. integration_position — де в відео (початок/середина/кінець)

Поверни у форматі JSON.
```

### 2.2 Аналіз емоційних характеристик

**Додатковий промпт для збагачення:**

```
Проаналізуй текст рекламної інтеграції та оціни за шкалою 1-10:
- urgency_score — рівень терміновості ("тільки зараз", "обмежена пропозиція")
- authenticity_score — наскільки нативно звучить
- storytelling_score — наскільки є наративна структура
- benefit_clarity — наскільки зрозумілі вигоди для глядача
- emotional_appeal — емоційний заряд
- specificity — конкретність (цифри, факти, кейси)

Також визнач:
- target_audience_implied — на кого орієнтована інтеграція
- key_selling_points — ключові аргументи (список)
- objection_handling — чи відпрацьовуються заперечення
```

---

## Фаза 3: Зіставлення з даними продажів

### 3.1 Структура зведеної таблиці

Фінальна Google Sheets таблиця повинна мати такі блоки колонок:

**Блок A — Ідентифікація:**
`video_id`, `platform`, `blogger_name`, `channel_subscribers`, `publish_date`, `campaign_name`

**Блок B — Метрики відео:**
`view_count`, `like_count`, `comment_count`, `engagement_rate` (розрахунковий)

**Блок C — Характеристики інтеграції (від LLM):**
`integration_text`, `tone`, `offer_type`, `offer_details`, `cta_type`, `personal_story`, `integration_position`, `urgency_score`, `authenticity_score`, `storytelling_score`, `benefit_clarity`, `emotional_appeal`, `specificity`

**Блок D — Дані продажів (з брифу):**
`leads_count`, `sales_count`, `revenue_usd`, `cost_usd`, `cpa`, `roas`

**Блок E — Розрахункові метрики:**
`cost_per_view`, `conversion_rate` (sales/views), `lead_to_sale_rate`, `revenue_per_1000_views`

### 3.2 Матчинг даних

Зв'язок між парсеними даними та продажами — через `video_url` або комбінацію `blogger_name + integration_date`. Необхідно уточнити з брифом формат зв'язку.

---

## Фаза 4: Кореляційний аналіз через Claude Opus 4.6

### 4.1 Підготовка контексту

Claude Opus 4.6 підтримує до 1 мільйона токенів контексту. Завантажити всю зведену таблицю як один контекст.

**Формат подачі:** CSV або JSON із усіма записами.

### 4.2 Аналітичний промпт

```
Тобі надано повну таблицю рекламних інтеграцій TripleTen з YouTube та Instagram.
Кожен рядок містить: метадані відео, повний текст інтеграції, LLM-оцінки характеристик
інтеграції та реальні дані продажів (ліди, продажі, виручка, CPA, ROAS).

Проведи глибокий аналіз і знайди:

1. КОРЕЛЯЦІЇ З ПРОДАЖАМИ:
   - Які характеристики інтеграцій найсильніше корелюють з високим ROAS?
   - Чи є залежність між тоном інтеграції та конверсією?
   - Який тип оферу (знижка/промокод/тріал) дає найкращий результат?
   - Чи впливає позиція інтеграції у відео (початок/середина/кінець)?
   - Чи є кореляція між наявністю особистої історії та конверсією?

2. ПАТЕРНИ УСПІШНИХ ІНТЕГРАЦІЙ:
   - Виділи топ-5 спільних рис інтеграцій з найвищим ROAS
   - Виділи топ-5 спільних рис інтеграцій з найнижчим ROAS
   - Порівняй сценарії: в чому текстова різниця між "тими що спрацювали" і "тими що ні"?
   - Чи є оптимальна тривалість інтеграції?

3. СЕГМЕНТАЦІЯ БЛОГЕРІВ:
   - Які типи каналів/блогерів дають найкращий ROI?
   - Чи є оптимальний розмір аудиторії (мікро vs макро-інфлюенсери)?
   - Тематична сегментація: які ніші каналів конвертять найкраще?

4. РЕКОМЕНДАЦІЇ:
   - Сформулюй конкретні guidelines для ідеального сценарію інтеграції
   - Запропонуй оптимальний бриф для блогера на основі даних
   - Вкажи, на що НЕ варто витрачати бюджет (анти-патерни)

5. АНОМАЛІЇ:
   - Чи є відео з високими переглядами але низькою конверсією? Що в них не так?
   - Чи є "темні конячки" — невеликі канали з вибуховим ROAS? Що в них спільного?

Відповідай з конкретними прикладами з даних. Де можливо — давай числа.
```

---

## Структура проєкту для Claude Code

```
tripleten-integration-analyzer/
├── README.md
├── requirements.txt
├── config/
│   └── config.yaml              # API ключі, налаштування
├── data/
│   ├── input/
│   │   ├── integrations_list.csv # Вхідний перелік інтеграцій
│   │   └── sales_data.csv        # Дані продажів з брифу
│   ├── raw/                      # Сирі парсені дані
│   ├── enriched/                 # Збагачені LLM-даними
│   └── output/
│       └── final_analysis.csv    # Зведена таблиця
├── src/
│   ├── parsers/
│   │   ├── youtube_parser.py     # YouTube Data API + Transcript API
│   │   ├── reels_parser.py       # Instagram Reels через Apify
│   │   └── base_parser.py        # Базовий клас парсера
│   ├── enrichment/
│   │   ├── llm_enricher.py       # Виділення інтеграцій + аналіз тону
│   │   └── prompts.py            # Промпти для LLM
│   ├── matching/
│   │   └── sales_matcher.py      # Матчинг з даними продажів
│   ├── analysis/
│   │   └── correlation_analyzer.py # Фінальний аналіз через Claude
│   └── export/
│       ├── sheets_exporter.py    # Експорт у Google Sheets
│       └── report_generator.py   # Генерація звіту
├── scripts/
│   ├── run_full_pipeline.py      # Повний пайплайн одною командою
│   └── run_analysis_only.py      # Тільки аналіз (якщо дані вже є)
└── tests/
    └── test_parsers.py
```

---

## Порядок виконання в Claude Code

### Крок 1: Ініціалізація проєкту
```bash
# Створити структуру, встановити залежності
mkdir -p tripleten-integration-analyzer/{config,data/{input,raw,enriched,output},src/{parsers,enrichment,matching,analysis,export},scripts,tests}
cd tripleten-integration-analyzer
pip install google-api-python-client youtube-transcript-api anthropic pandas gspread
```

### Крок 2: YouTube Parser
- Реалізувати `youtube_parser.py`
- На вході: `integrations_list.csv` (колонка з URL)
- На виході: `data/raw/youtube_raw.json` (метадані + транскрипти)
- Обробка помилок: відео без транскрипту, приватні відео, rate limits

### Крок 3: LLM Enrichment
- Реалізувати `llm_enricher.py` з використанням Anthropic API
- Промпти з файлу `prompts.py`
- Батч-обробка з retry-логікою та rate limit handling
- На виході: `data/enriched/enriched_integrations.json`

### Крок 4: Матчинг з продажами
- Реалізувати `sales_matcher.py`
- Злити парсені + збагачені дані з `sales_data.csv`
- Розрахувати метрики (engagement_rate, CPA, ROAS, conversion_rate)
- На виході: `data/output/final_analysis.csv`

### Крок 5: Кореляційний аналіз
- Реалізувати `correlation_analyzer.py`
- Завантажити `final_analysis.csv` як контекст у Claude Opus 4.6
- Використати аналітичний промпт із Фази 4
- На виході: структурований звіт (markdown + key findings)

### Крок 6: Експорт та звіт
- Google Sheets: зведена таблиця з усіма даними
- Markdown-звіт з ключовими знахідками та рекомендаціями
- Опціонально: візуалізації (matplotlib/plotly)

---

## Вхідні дані, які потрібні від замовника

1. **Список URL усіх рекламних інтеграцій** (YouTube + Instagram Reels)
2. **Дані продажів у зіставному форматі** (CSV/Excel): які відео → скільки лідів → скільки продажів → яка виручка
3. **YouTube Data API ключ** (безкоштовний, створюється в Google Cloud Console)
4. **Anthropic API ключ** (для збагачення через Claude)
5. **Уточнення розбіжності в цифрах:** Excel показує ~497K, Notion-аналіз ~563K — різниця ~56-66K потребує перевірки перед аналізом

---

## Очікуваний результат

1. **Автоматизований парсер** — збирає дані одною командою, легко оновлюється при появі нових інтеграцій
2. **Зведена Google Sheets таблиця** — з усіма метриками, LLM-оцінками та даними продажів
3. **Аналітичний звіт** — конкретні кореляції, патерни успіху/провалу, рекомендації для майбутніх інтеграцій
4. **Guidelines для брифу блогерам** — data-driven рекомендації щодо ідеального сценарію інтеграції
5. **Вау-ефект для TripleTen** — AI-powered аналіз, який демонструє технічну експертизу

---

## Технічні примітки

- **YouTube Transcript API** — безкоштовний, не потребує API ключа, але не всі відео мають субтитри (особливо українською). Fallback: Whisper API для транскрибування аудіо.
- **Apify** — freemier дає 30 секунд compute/місяць, достатньо для десятків відео. Є ready-made актори для YouTube і Instagram.
- **GPT for Google Sheets** — extension, який дозволяє викликати GPT прямо в клітинках таблиці. Альтернатива: batch-обробка через API.
- **Claude Opus 4.6** — контекст до 1M токенів, ідеально для аналізу великих датасетів одним запитом.
- **Rate limits:** YouTube Data API — 10,000 units/день (безкоштовно). Один video.list = 1 unit. Transcript API — без лімітів.
