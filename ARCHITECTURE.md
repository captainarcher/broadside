# Broadside Architecture

**Broadside** is a Python CLI tool that automates the full content pipeline for two satirical shows:

- **That's The BS** — daily, vertical 9:16
- **The Audit Trail** — pro-track, horizontal 16:9

The tool covers news sourcing, comedy writing, editorial illustration, parody ad generation, avatar video rendering, video assembly with captions, and multi-platform publishing. The human owns taste and publishing decisions; Broadside owns rendering and assembly.

---

## Table of Contents

1. [System 1: Content Creation](#system-1-content-creation)
   - [News Sourcing Pipeline](#news-sourcing-pipeline)
   - [Joke Writing Pipeline](#joke-writing-pipeline)
   - [Editorial Illustration Generation](#editorial-illustration-generation)
   - [Parody Ad Generation](#parody-ad-generation)
2. [System 2: Rendering (HeyGen v3)](#system-2-rendering)
3. [System 3: Assembly (Descript + FFmpeg)](#system-3-assembly)
4. [System 4: Publishing](#system-4-publishing)
5. [System 5: Operations](#system-5-operations)
6. [Episode Input Format](#episode-input-format)
7. [Config File](#config-file)
8. [Tech Stack](#tech-stack)
9. [Project Structure](#project-structure)
10. [CLI Command Reference](#cli-command-reference)
11. [Acceptance Tests](#acceptance-tests)
12. [Environment Variables](#environment-variables)
13. [Onboarding Checklist](#onboarding-checklist)
14. [Cost Summary](#cost-summary)
15. [What Broadside Must Never Do](#what-broadside-must-never-do)

---

## System 1: Content Creation

News sourcing, joke writing, editorial illustrations, and parody ads.

### News Sourcing Pipeline

**Primary sources:**

| Source | Integration |
|--------|------------|
| Reddit (r/nottheonion, r/technology, r/science, r/offbeat) | PRAW |
| Hacker News | Firebase API (top N stories) |
| Google News | RSS via feedparser |
| NewsData.io | REST API |

**Supplementary sources:** UPI Odd News RSS, Ars Technica RSS, The Verge RSS (all via feedparser).

**Deduplication:** URL normalization followed by TF-IDF title similarity using scikit-learn. Stories with cosine similarity above 0.85 are flagged as duplicates.

**Political filter (3-tier):**

1. **Category exclusion** at the source level (skip political subreddits/categories)
2. **Keyword blocklist** loaded from `config/political-keywords.txt`
3. **LLM classification** via Claude Haiku for edge cases that pass tiers 1 and 2

**Satire ranker:** Each story receives a weighted composite score:

| Dimension | Weight |
|-----------|--------|
| Absurdity | 30% |
| Popularity | 25% |
| Irony potential | 20% |
| Topicality | 15% |
| Talkability | 10% |

Scoring is batched through the LLM to minimize API calls (one call per batch of stories rather than per story).

**Output:** Daily digest of the top 15-20 stories with satire scores, delivered to the configured notification channel.

**CLI:**
- `broadside scout` — run the full news pipeline
- `broadside scout --dry-run` — list sources and estimated story count, make zero network calls

### Joke Writing Pipeline

Multi-pass comedy generation using the Claude API. Each pass has a distinct role:

| Pass | Purpose | Model |
|------|---------|-------|
| 1. Angle mining | Generate 8-12 satirical angles per story | Claude Sonnet |
| 2. Joke generation | 3-5 joke variants per selected angle, different comedy structures | Claude Sonnet |
| 3. Script assembly | Selected jokes assembled into episode beat structure | Claude Sonnet |
| 4. Voice polish | Rewrite in Benn Stone's voice using character sheet + example bank | Claude Opus |

**Comedy menu output:** The pipeline produces multiple options per beat position. The human selects, edits, or rejects options before final assembly.

**Character sheet:** Maintained as YAML at `config/benn-stone.yaml`, included in every prompt context.

**Example bank:** 10-20 gold-standard scripts stored in `examples/`. A rotating subset is used as few-shot examples in prompts.

**Word count calibration:**

| Target Duration | Word Count |
|----------------|------------|
| 60 seconds | ~140 words |
| 75 seconds | ~180 words |
| 90 seconds | ~210 words |

Word counts account for `pause_after` values in the scene schema.

**Output:** Draft episode YAML conforming to the episode schema, deposited in `episodes/drafts/`.

**CLI:**
- `broadside write <story-url-or-id>` — interactive multi-pass writing for a single story
- `broadside write --batch` — process all scouted stories

### Editorial Illustration Generation

"Court reporter sketch" style editorial illustrations for each episode, generated via Replicate.

**Model:** Flux 2 Pro (`black-forest-labs/flux-2-pro`) via the Replicate API.

**Style consistency:** Up to 8 style reference images stored in `assets/style-references/`. All prompts include a fixed style prefix:

> Editorial courtroom sketch style, colored pencil and charcoal on cream textured paper, loose expressive strokes, muted earth tones with selective color accents, dramatic chiaroscuro lighting

**Aspect ratio:** 9:16 for BS episodes, 16:9 for Audit Trail episodes (driven by show config).

**Output:** 2-3 images per episode in `assets/illustrations/<episode-id>/`.

**Cost:** ~$0.03-0.055 per image, ~$0.10-0.15 per episode.

**Future enhancement:** Fine-tune a model on Replicate for even greater style consistency.

**CLI:** `broadside illustrate <episode.yaml>`

### Parody Ad Generation

Fully AI-generated satirical sponsor ads (10-15 seconds each). These are fake products with intentionally absurd premises.

**Sub-pipeline:**

1. **Script generation** — Claude API creates product name, tagline, voiceover script, and text overlay copy
2. **Product images** — Replicate Flux 2 Pro generates 3 images (product shot, logo, lifestyle scene)
3. **Voiceover** — ElevenLabs API with dramatic announcer voice (Eleven v3 model)
4. **Jingle** — Replicate MusicGen (instrumental) or Suno API (with lyrics)
5. **Assembly** — FFmpeg composites everything with Ken Burns effects on product images, text overlays, cheesy infomercial transitions, and optional VHS degradation filter

**Storage:**
- Ad concepts stored as YAML in `ads/concepts/`
- Rendered ads stored in `ads/rendered/`

**Cost:** ~$0.25-0.45 per ad.

**CLI:**
- `broadside ad <concept.yaml>` — generate a specific parody ad
- `broadside ad --random` — pick a random concept from the concept bank

---

## System 2: Rendering

Avatar video rendering via the HeyGen v3 API.

### HeyGen v3 Integration

**API endpoint:** `POST /v3/videos` with type `"avatar"`.

**Architecture decision:** One API call per talk scene (not multi-scene). This gives full assembly control — scenes can be reordered, replaced, or individually re-rendered without touching others.

**Per-show configuration:** Each show defines its own `avatar_id`, `voice_id`, `aspect_ratio`, `background_color` (#0D1B2A), and `engine` tier in `config.yaml`.

**Content-hash idempotency:** Each rendered scene filename includes `SHA256(scene_text + avatar_id + voice_id)[:12]`. On re-run, if the hash matches an existing file, that scene is skipped entirely — no API call, no spend.

**Concurrency:** `asyncio` + `httpx` with `asyncio.Semaphore(10)` to respect HeyGen's 10-concurrent-video limit.

**Polling:** Exponential backoff starting at 5 seconds, doubling up to 60 seconds. The system also supports `callback_url` webhooks for notification-based completion.

**Idempotency-Key:** Sent as an HTTP header on all create calls, enabling safe retries on network failures.

**Scene text:** Passed verbatim to HeyGen. The episode YAML is responsible for writing out numbers, abbreviations, etc.

**Startup verification:** Before rendering, the system calls `GET /v3/avatars/looks` and `GET /v3/voices` to confirm that the configured avatar and voice IDs actually exist. Fails fast with a clear error if not.

**Output:**
- Scene files: `build/<episode>/scenes/<id>-<hash>.mp4`
- Manifest: `build/<episode>/render-manifest.json`

**Cost tracking:** Avatar IV costs ~$0.05-0.067/sec, Avatar III costs ~$0.017-0.043/sec. Cost is logged per scene in the render manifest.

**CLI:**
- `broadside render <episode.yaml>` — render all scenes
- `broadside render <episode.yaml> --dry-run` — print plan + cost estimate, make zero network calls
- `broadside render <episode.yaml> --yes` — skip interactive confirmation (budget rails still enforced)
- `broadside retry <episode> <scene>` — re-render a single scene

---

## System 3: Assembly

Video assembly with two engines: Descript API (primary) and FFmpeg (fallback).

### Descript API Path

**Auth:** Bearer token from `DESCRIPT_API_TOKEN` environment variable, scoped to a specific Descript Drive.

**API surface** (documented at docs.descriptapi.com):

| Endpoint | Purpose |
|----------|---------|
| `POST /v1/jobs/import/project_media` | Import scene MP4s into project |
| `POST /v1/jobs/agent` | Underlord AI editing (captions, effects, Studio Sound) |
| `POST /v1/jobs/publish` | Publish/export project |
| `GET /v1/jobs/{job_id}` | Poll job status |
| `GET /v1/agent/models` | List available Underlord models |
| `POST /v1/export/transcript` | Export transcript/captions |

**Important caveats:** The Descript API is Underlord/prompt-driven and in early access. Nondeterminism is a real concern. A **feasibility spike is required** to test each operation for repeatability before relying on it in production.

**Mitigation:**
- Pin exact prompts/operations in config — never use freeform Underlord calls
- Log which engine (Descript vs FFmpeg) handled each step in the manifest
- Fall back to FFmpeg for any operation that proves unreliable

### FFmpeg Fallback

FFmpeg handles everything Descript cannot do deterministically (and serves as the complete fallback).

**Timeline construction:** Concatenate rendered scene MP4s in episode order.

**Pause handling:** `pause_after` values extend the last frame of a scene using the `tpad` filter.

**Card scenes:** Full-screen still images with 100ms fade-in/fade-out.

**Silent scenes:** Freeze-frames with optional overlay asset composited on top.

**Zoom:** Flagged scenes (`zoom: true`) get a 112% center crop/scale, hard cut in/out — no animated zoom, just a punched-in frame.

**Captions:** Word-by-word karaoke-style captions generated via faster-whisper in **alignment mode only**. The words are already known from the script; faster-whisper provides only timing data.

- Format: ASS subtitles burned into the video
- Font: bold condensed, centered in the middle-lower third
- Current word highlighted in the show's accent color (BS: `#E63946`, Audit Trail: `#4A7DA8`)
- Captions are suppressed during card scenes and end cards

**End card:** Brand background color with wordmark in the upper third, text line below, duration specified in YAML.

**Audio:**
- Normalize all audio to -16 LUFS
- Optional music bed ducked -20dB under speech

**Contact sheet:** Generate a thumbnail PNG grid of keyframes for quick visual review.

**Output:** `build/<episode>/final-<episode>.mp4` — H.264 at 1080p, yuv420p pixel format, faststart moov atom.

**CLI:**
- `broadside assemble <episode.yaml>` — assemble with auto engine selection
- `broadside assemble <episode.yaml> --engine descript` — force Descript
- `broadside assemble <episode.yaml> --engine ffmpeg` — force FFmpeg
- `broadside assemble <episode.yaml> --engine auto` — try Descript, fall back to FFmpeg

---

## System 4: Publishing

All publishing is **human-initiated**. The `broadside publish` command requires explicit platform selection and confirmation. The tool never auto-posts, even in `--yes` mode.

### YouTube (Official API)

**Auth:** OAuth 2.0 via `google-api-python-client` + `google-auth-oauthlib`. Scope: `youtube.upload`. One-time browser OAuth flow; refresh tokens stored in `~/.broadside/tokens/`.

**Upload:** Resumable upload protocol.

**Metadata:** title, description, tags, categoryId, privacyStatus, selfDeclaredMadeForKids, containsSyntheticMedia. Supports scheduled publishing via `publishAt`.

**Rate limit:** ~6 uploads/day (1600 units per upload, 10K daily quota).

**No app review needed** for personal use (Google Cloud project in Testing mode).

### X / Twitter (Official API)

**Auth:** OAuth 1.0a for media upload + OAuth 2.0 for tweet creation.

**Upload flow:** Chunked media upload: INIT, APPEND (in chunks), FINALIZE, then STATUS poll until processing completes. Then `POST /2/tweets` with `media.media_ids`.

**Limits:** Max 512MB, 140 seconds, H.264/AAC. Rate: 200 tweets per 15 minutes.

**Library:** tweepy. Developer account required (free tier works for posting).

### Instagram (Playwright Browser Automation)

Instagram web supports Reel uploads from desktop.

**Auth:** Cookie-based. Export `sessionid` cookie from browser, load into Playwright session.

**Stealth:** Playwright with stealth plugin or headed mode to avoid detection.

**Automation flow:** Navigate to create, upload video, set caption and hashtags, publish.

**Cookie refresh:** Needed periodically — re-export from browser via `broadside auth refresh instagram`.

**Risk:** Low at 5-7 uploads per week with cookie auth and headed mode.

### TikTok (Playwright Browser Automation)

**Auth:** Cookie-based Playwright automation following tiktok-uploader / TikTokAutoUploader patterns. Export `sessionid` cookie from browser.

**Automation flow:** Navigate to upload page, upload video, set caption/hashtags/visibility, publish. Supports scheduling up to 10 days out.

**Detection avoidance:** Fingerprint spoofing + human-like delays between actions.

**Risk:** Low at 5-7 uploads per week with cookie auth.

### Browser Automation Resilience

- **Primary:** Scripted Playwright with CSS selectors
- **Fallback:** browser-use library (LLM-driven browser agent) if selectors break due to UI changes

All browser sessions run **headed** on the local machine (not headless).

### Cookie Management

- `broadside auth setup <platform>` — guided cookie import from browser
- `broadside auth check` — verify all platform tokens/cookies are valid
- `broadside auth refresh <platform>` — re-import cookies

### Publish Flow

- `broadside publish <episode> --platform youtube,x,instagram,tiktok` — publish to specified platforms
- `broadside publish <episode> --all` — publish to all configured platforms
- Interactive confirmation per platform showing preview (title, caption, thumbnail)
- Platform-specific metadata generated from episode YAML (caption_hook becomes caption, etc.)
- **Never auto-publishes**, even in `--yes` mode
- All published URLs logged in `out/<episode>/publish-manifest.json`

---

## System 5: Operations

Watch folders, scheduling, budget enforcement, notifications, and run management.

### Watch Folder Convention

```
episodes/
  drafts/       # YAML drafts land here -- NEVER rendered
  approved/     # Human moves file here = approval. Cron renders ONLY from here.
  rendered/     # Completed YAML moves here with manifest
build/          # Scene files + finals per episode
out/            # Final MP4s + caption hooks in sidecar .txt
ads/
  concepts/     # Parody ad concept YAMLs
  rendered/     # Completed parody ad MP4s
assets/         # Brand assets, cards, illustrations, style references
```

Moving a file from `drafts/` to `approved/` is the entire human approval workflow. **The tool never renders from `drafts/`.**

### Budget System (Non-negotiable Rails)

**Interactive runs:** Print estimated cost and require confirmation before proceeding.

**Unattended runs** (`--yes` or cron): Skip the prompt but enforce hard caps:

| Guard | Default | Config Key |
|-------|---------|------------|
| Per-batch cap | $25 | `budget.max_batch_usd` |
| Weekly rolling cap | $40 | `budget.max_weekly_usd` |

**Spend ledger:** `~/.broadside/spend.json` — rolling weekly window of all API spend.

**Over-budget behavior:** Exit non-zero with a clear summary of current spend vs. cap. Never silently skip work.

**Tracked services:** HeyGen renders, Replicate images, ElevenLabs voice, Claude API, Descript credits.

### Scheduling

`broadside install-schedule` writes the correct scheduler entry for the host OS:

| OS | Scheduler |
|----|-----------|
| macOS | launchd plist |
| Linux | systemd timer |
| Fallback | crontab line |

**Default schedule:** Sunday 9pm, running `broadside run --yes`.

All runs are **idempotent and resumable** via a state file that tracks per-scene render status.

### The `broadside run` Command

Single command that orchestrates the full pipeline:

1. Scan `episodes/approved/` for unprocessed episode YAMLs
2. Render all scenes via HeyGen
3. Assemble final video via Descript/FFmpeg
4. Output to `out/`
5. Write `out/SUMMARY-<date>.md`

**Flags:**
- `broadside run --dry-run` — preview plan + cost estimate, no network calls
- `broadside run --yes` — unattended mode with budget rails enforced

### Notifications

Config-driven via `config.notify`:

| Type | Mechanism |
|------|-----------|
| `osascript` | macOS native notification |
| `webhook` | HTTP POST to Slack/Discord/ntfy URL |
| `smtp` | Plain SMTP email |

**Failure notifications** include the error message and which specific scene failed. Partial success still delivers completed episodes and notifies about the partial result.

### Dry-Run Mode

`--dry-run` on any command: validate all inputs, print the full execution plan with cost estimate, make **zero network calls**.

### Idempotency and Resumability

- **Content-hash filenames** for rendered scenes (no re-render if content unchanged)
- **State file** tracks per-scene status: pending, rendering, complete, or failed
- Re-running skips all completed scenes
- **Process kill mid-batch** is safe: next run resumes without re-billing completed scenes

---

## Episode Input Format

Episodes are defined as YAML files conforming to this schema:

```yaml
episode: ep03-two-million-tokens
show: bs            # bs | audit-trail
post_day: Thursday
caption_hook: "Google's AI can read 20 novels at once. I have my reasons."
source_story:
  headline: "Original news headline"
  source: "Publication"
  url: "https://..."
scenes:
  - id: s1
    type: talk
    text: "I'm Benn Stone, and this is your daily BS."
  - id: s2
    type: talk
    text: "Google launched Gemini three point five Pro this week..."
    pause_after: 1.0
  - id: s3
    type: talk
    text: "...page forty. It's not the length."
    zoom: true
    pause_after: 1.2
  - id: s4
    type: card
    asset: assets/cards/sponsor-blinkonce.png
    duration: 2.0
    audio: none     # none | continue
  - id: s5
    type: talk
    text: "Today's sponsor: BlinkOnce Audiobooks..."
  - id: s6
    type: silent
    duration: 1.0
    overlay: assets/cards/ep4-upgrade-card-1080x1920.png
  - id: s7
    type: talk
    text: "I'm Benn Stone, and that's the BS."
  - id: s8
    type: ad
    concept: ads/concepts/blinkonce.yaml
    duration: 12.0
end_card:
  wordmark: assets/brand/wordmark-transparent.png
  text: "@thatsthebs . New every weekday"
  duration: 2.0
```

**Scene types:**

| Type | Description | Rendered by |
|------|-------------|------------|
| `talk` | Avatar speaks the text | HeyGen |
| `card` | Full-screen still image | FFmpeg (hold + fade) |
| `silent` | Freeze-frame with optional overlay | FFmpeg |
| `ad` | Parody ad insertion (references concept YAML) | Ad pipeline + FFmpeg |

**Optional fields on talk scenes:**
- `pause_after` (float, seconds) — extend last frame after speech
- `zoom` (bool) — 112% center crop for emphasis

---

## Config File

Main configuration lives at `config/config.yaml`:

```yaml
shows:
  bs:
    avatar_id: "avatar_look_id_here"
    voice_id: "voice_id_here"
    aspect_ratio: "9:16"
    dimensions: [1080, 1920]
    engine: "avatar_iv"
    cost_per_sec: 0.05
    background_color: "#0D1B2A"
    caption:
      font: "assets/fonts/condensed-bold.ttf"
      size: 48
      y_position: 0.75
      highlight_color: "#E63946"
    brand:
      wordmark: "assets/brand/bs-wordmark.png"
      end_text: "@thatsthebs . New every weekday"

  audit-trail:
    avatar_id: "avatar_look_id_here"
    voice_id: "voice_id_here"
    aspect_ratio: "16:9"
    dimensions: [1920, 1080]
    engine: "avatar_iv"
    cost_per_sec: 0.05
    background_color: "#0D1B2A"
    caption:
      font: "assets/fonts/condensed-bold.ttf"
      size: 42
      y_position: 0.80
      highlight_color: "#4A7DA8"
    brand:
      wordmark: "assets/brand/audit-wordmark.png"
      end_text: "@theaudittrail"

budget:
  max_batch_usd: 25
  max_weekly_usd: 40

notify:
  - type: osascript
  - type: webhook
    url: "https://hooks.slack.com/services/..."
  - type: smtp
    host: smtp.gmail.com
    port: 587
    to: "benn@example.com"

news:
  sources:
    reddit:
      subreddits: ["nottheonion", "technology", "science", "offbeat"]
    hackernews:
      top_n: 200
    google_news:
      topics: ["technology", "business", "science", "entertainment"]
    newsdata:
      categories: ["technology", "business", "science", "entertainment"]
  political_filter:
    keywords_file: "config/political-keywords.txt"
    llm_classification: true

comedy:
  model_angles: "claude-sonnet-4-6"
  model_jokes: "claude-sonnet-4-6"
  model_assembly: "claude-sonnet-4-6"
  model_polish: "claude-opus-4-6"
  character_sheet: "config/benn-stone.yaml"
  example_bank: "examples/"
  duration_target: 75

illustrations:
  model: "black-forest-labs/flux-2-pro"
  style_references: "assets/style-references/"
  style_prefix: >-
    Editorial courtroom sketch style, colored pencil and charcoal on cream
    textured paper, loose expressive strokes, muted earth tones with selective
    color accents, dramatic chiaroscuro lighting

ads:
  voice_provider: "elevenlabs"
  voice_id: "dramatic-announcer-voice-id"
  music_model: "facebook/musicgen-medium"
  vhs_filter: true
  concept_bank: "ads/concepts/"

publishing:
  youtube:
    privacy: "private"
    category_id: "24"
    made_for_kids: false
    contains_synthetic_media: true
  x:
    # configured via broadside auth setup x
  instagram:
    browser: "headed"
  tiktok:
    browser: "headed"
    default_visibility: "public"
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.13+ |
| CLI framework | click |
| HTTP client | httpx (async) |
| Schema validation | pydantic v2 |
| HeyGen integration | Direct REST API v3 via httpx |
| Descript integration | Direct REST API v1 via httpx (with feasibility spike) |
| Image generation | replicate Python SDK (Flux 2 Pro) |
| Voice synthesis | elevenlabs Python SDK |
| LLM (comedy + scoring) | anthropic Python SDK |
| YouTube upload | google-api-python-client + google-auth-oauthlib |
| X/Twitter posting | tweepy |
| Instagram/TikTok automation | playwright (with stealth) |
| Reddit sourcing | praw |
| RSS parsing | feedparser |
| Article extraction | newspaper4k |
| Deduplication | scikit-learn (TF-IDF vectorizer + cosine similarity) |
| Caption timing | faster-whisper (alignment mode only) |
| Video processing | ffmpeg via subprocess |
| Audio processing | ffmpeg (LUFS normalization, ducking) |
| Config management | pydantic-settings (YAML loading) |
| Budget ledger | JSON file in ~/.broadside/ |
| Scheduling | launchd / systemd / cron |

---

## Project Structure

```
broadside/
├── broadside/                  # Python package
│   ├── __init__.py
│   ├── cli.py                  # Click CLI entrypoint -- all commands
│   ├── config.py               # Pydantic config model
│   ├── schema.py               # Episode YAML + ad concept schemas
│   │
│   ├── scout/                  # News sourcing pipeline
│   │   ├── __init__.py
│   │   ├── sources.py          # Reddit, HN, Google News, NewsData fetchers
│   │   ├── dedup.py            # TF-IDF deduplication
│   │   ├── filter.py           # Political content filter
│   │   ├── ranker.py           # Satire potential scorer
│   │   └── digest.py           # Daily digest output
│   │
│   ├── writer/                 # Comedy writing pipeline
│   │   ├── __init__.py
│   │   ├── angles.py           # Pass 1: angle mining
│   │   ├── jokes.py            # Pass 2: joke generation
│   │   ├── assembly.py         # Pass 3: script assembly
│   │   ├── polish.py           # Pass 4: voice polish
│   │   └── character.py        # Character sheet + example bank loader
│   │
│   ├── illustrate/             # Editorial illustration generation
│   │   ├── __init__.py
│   │   └── flux.py             # Replicate Flux 2 Pro integration
│   │
│   ├── ads/                    # Parody ad generation
│   │   ├── __init__.py
│   │   ├── scriptgen.py        # Ad script generation (Claude)
│   │   ├── assets.py           # Product image generation (Flux)
│   │   ├── voice.py            # Voiceover generation (ElevenLabs)
│   │   ├── music.py            # Jingle generation (MusicGen)
│   │   └── compose.py          # FFmpeg assembly with infomercial effects
│   │
│   ├── render/                 # HeyGen scene rendering
│   │   ├── __init__.py
│   │   ├── heygen.py           # HeyGen v3 API client
│   │   ├── hasher.py           # Content hash for idempotency
│   │   └── poller.py           # Async polling with backoff
│   │
│   ├── assemble/               # Video assembly
│   │   ├── __init__.py
│   │   ├── descript.py         # Descript API client
│   │   ├── ffmpeg.py           # FFmpeg assembly pipeline
│   │   ├── captions.py         # faster-whisper alignment + ASS generation
│   │   ├── endcard.py          # End card generation
│   │   └── contact_sheet.py    # Thumbnail grid for review
│   │
│   ├── publish/                # Multi-platform publishing
│   │   ├── __init__.py
│   │   ├── youtube.py          # YouTube Data API v3
│   │   ├── twitter.py          # X/Twitter API
│   │   ├── instagram.py        # Playwright browser automation
│   │   ├── tiktok.py           # Playwright browser automation
│   │   ├── cookies.py          # Cookie import/management
│   │   └── browser.py          # Shared Playwright + stealth setup
│   │
│   ├── budget.py               # Spend tracking, budget guards
│   ├── state.py                # Run state file for idempotency/resume
│   ├── manifest.py             # Render/publish manifest read/write
│   ├── notify.py               # Notification dispatch (osascript, webhook, smtp)
│   └── scheduler.py            # Schedule installer (launchd, systemd, cron)
│
├── config/
│   ├── config.yaml             # Main configuration
│   ├── benn-stone.yaml         # Character sheet
│   └── political-keywords.txt  # Political filter keywords
│
├── examples/                   # Gold-standard episode scripts (few-shot bank)
│
├── episodes/
│   ├── drafts/
│   └── approved/
│
├── ads/
│   └── concepts/               # Parody ad concept YAMLs
│
├── assets/
│   ├── brand/                  # Wordmarks, logos
│   ├── cards/                  # Sponsor/gag cards
│   ├── fonts/                  # Caption fonts
│   ├── illustrations/          # Generated editorial illustrations
│   ├── style-references/       # Flux style reference images
│   └── overlays/               # Infomercial graphics for parody ads
│
├── build/                      # Scene MP4s + manifests (gitignored)
├── out/                        # Final MP4s + publish manifests (gitignored)
│
├── tests/
│   ├── test_dry_run.py
│   ├── test_budget.py
│   ├── test_idempotency.py
│   ├── test_schema.py
│   ├── test_dedup.py
│   ├── test_political_filter.py
│   └── fixtures/               # Test episode YAMLs, mock responses
│
├── pyproject.toml
├── .gitignore
├── .env.example
├── ARCHITECTURE.md             # This document
└── README.md
```

---

## CLI Command Reference

```
broadside scout                                              # Run news sourcing pipeline
broadside scout --dry-run                                    # Preview sources, no fetching
broadside write <story>                                      # Interactive joke writing for a story
broadside write --batch                                      # Process all scouted stories
broadside illustrate <episode>                               # Generate editorial illustrations
broadside ad <concept.yaml>                                  # Generate a parody ad
broadside ad --random                                        # Random concept from bank
broadside render <episode> [--dry-run] [--yes]               # Render scenes via HeyGen
broadside assemble <episode> [--engine auto|descript|ffmpeg]  # Assemble final video
broadside publish <episode> --platform youtube,x,instagram,tiktok  # Human-initiated publish
broadside publish <episode> --all                            # Publish to all configured platforms
broadside run [--dry-run] [--yes]                            # Full pipeline: approved/ -> render -> assemble -> output
broadside retry <episode> <scene>                            # Re-render a single scene
broadside auth setup <platform>                              # Guided auth/cookie setup
broadside auth check                                         # Verify all credentials
broadside auth refresh <platform>                            # Re-import cookies
broadside budget                                             # Show current spend summary
broadside budget --history                                   # Weekly spend history
broadside install-schedule                                   # Install cron/launchd/systemd schedule
broadside onboard                                            # Guided setup: create accounts, set API keys, verify access
```

---

## Acceptance Tests

1. `broadside scout --dry-run` lists sources and estimated story count, makes zero network calls
2. `broadside render --dry-run` of a 3-scene fixture prints plan + cost, makes zero network calls
3. A scene text change re-renders only that scene; unchanged re-run renders nothing, spends nothing
4. Assembled fixture: pauses measurably extend scenes; card holds exactly its duration; captions never overlap cards; zoom scene is visibly punched in
5. Batch exceeding per-batch cap OR pushing weekly spend past weekly cap refuses with clear message and non-zero exit — in both interactive and `--yes` modes
6. A YAML in `drafts/` is never rendered, even when named identically to one in `approved/`
7. Kill process mid-batch; next run resumes without re-billing completed scenes
8. `grep -r` the repo for API key strings: zero hits outside env usage
9. Parody ad generation produces a playable MP4 with voiceover, music, and product images
10. `broadside publish --platform youtube` uploads video and returns URL (requires confirmation)
11. Political filter correctly blocks political stories and passes tech/business/weird stories
12. `broadside onboard` walks through all account setup with verification steps

---

## Environment Variables

These are never written to disk, logs, or git:

```
HEYGEN_API_KEY          # HeyGen v3 API
DESCRIPT_API_TOKEN      # Descript API (scoped to specific Drive)
REPLICATE_API_TOKEN     # Replicate (Flux, MusicGen)
ELEVENLABS_API_KEY      # ElevenLabs TTS
OPENROUTER_API_KEY      # OpenRouter (LLM access — comedy writing, scoring, classification)
GOOGLE_CLIENT_ID        # YouTube OAuth
GOOGLE_CLIENT_SECRET    # YouTube OAuth
TWITTER_API_KEY         # X/Twitter OAuth 1.0a
TWITTER_API_SECRET      # X/Twitter OAuth 1.0a
TWITTER_ACCESS_TOKEN    # X/Twitter user token
TWITTER_ACCESS_SECRET   # X/Twitter user token secret
REDDIT_CLIENT_ID        # Reddit/PRAW
REDDIT_CLIENT_SECRET    # Reddit/PRAW
NEWSDATA_API_KEY        # NewsData.io
```

---

## Onboarding Checklist

When the user runs `broadside onboard`, guide them through each step with verification:

1. **HeyGen** — Sign up at heygen.com, get API key from Settings > API, fund wallet
2. **Replicate** — Sign up at replicate.com, get API token, add payment method
3. **ElevenLabs** — Sign up at elevenlabs.io, get API key, select/create dramatic announcer voice
4. **Anthropic/Claude** — Get API key from console.anthropic.com
5. **Descript** — Sign up for paid plan, create API token in Settings > API Tokens (note which Drive)
6. **YouTube** — Create Google Cloud project, enable YouTube Data API v3, create OAuth credentials, run auth flow
7. **X/Twitter** — Apply for developer account at developer.x.com, create app with Read+Write, get tokens
8. **Instagram** — Export cookies from browser using cookie export extension, import via `broadside auth setup instagram`
9. **TikTok** — Export cookies from browser, import via `broadside auth setup tiktok`
10. **Reddit** — Register app at reddit.com/prefs/apps, get client_id and secret
11. **NewsData.io** — Sign up at newsdata.io, get free API key
12. **FFmpeg** — Verify ffmpeg is installed (`brew install ffmpeg` on macOS)
13. **Fonts** — Install required caption fonts to `assets/fonts/`
14. **Style references** — Add 3-5 court reporter sketch images to `assets/style-references/`
15. **Example bank** — Add initial gold-standard scripts to `examples/`
16. **Config** — Fill in `config.yaml` with all IDs (avatar, voice, etc.)
17. **Verify** — `broadside auth check` to validate all credentials

Each step verifies success before proceeding to the next.

---

## Cost Summary

Estimated weekly costs for 5 BS episodes:

| Component | Per Episode | Weekly (5 eps) | Monthly (~22 eps) |
|-----------|------------|----------------|-------------------|
| News sourcing (LLM scoring) | ~$0.03 | ~$0.15 | ~$0.65 |
| Comedy writing (Claude API) | ~$0.45 | ~$2.25 | ~$10 |
| Illustrations (Replicate Flux) | ~$0.12 | ~$0.60 | ~$2.60 |
| Parody ads (all services) | ~$0.35 | ~$1.75 | ~$7.70 |
| HeyGen rendering (~60s/ep) | ~$3.50 | ~$17.50 | ~$77 |
| FFmpeg assembly | $0 | $0 | $0 |
| **Total** | **~$4.45** | **~$22.25** | **~$98** |

HeyGen is the dominant cost. The Avatar III engine cuts rendering to ~$1.00-2.50/ep if quality is acceptable.

---

## What Broadside Must Never Do

- Generate or alter joke text without human review
- Post, upload, or schedule anything to social platforms automatically (publish is always human-initiated)
- Spend or consume credits without budget rails
- Auto-run anything from `drafts/`
- Write API keys to disk, logs, or git
- The human owns taste and publishing; the tool owns rendering and assembly
