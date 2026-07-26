# Broadside

Automated video production pipeline for satirical news shows.

Broadside takes a news story and turns it into a finished, captioned, card-inserted vertical video with zero manual editing. It handles the full pipeline: news sourcing, comedy writing, editorial illustrations, parody ad generation, AI avatar rendering, video assembly with karaoke captions, and multi-platform publishing.

The human owns taste and publishing. Broadside owns rendering and assembly.

## What It Does

```
News Story --> Joke Writing --> Episode Script --> Avatar Rendering --> Video Assembly --> Publish
     ^              ^                ^                   ^                    ^              ^
  broadside      broadside       broadside           broadside           broadside      broadside
    scout          write         illustrate            render             assemble        publish
```

**Content Creation** -- Scout news from Reddit, Hacker News, Google News, and NewsData.io. Filter out politics. Rank by satirical potential. Write jokes in a 4-pass LLM pipeline. Generate court-reporter-sketch editorial illustrations. Auto-generate parody sponsor ads.

**Rendering** -- Send each scene to HeyGen's AI avatar API. One video per scene for full assembly control. Content-hash idempotency means re-runs skip already-rendered scenes.

**Assembly** -- Concatenate scenes with pauses, sponsor cards, zoom punch-ins, and word-by-word karaoke captions. FFmpeg handles everything deterministically.

**Publishing** -- Human-initiated uploads to YouTube (official API), X/Twitter (official API), Instagram and TikTok (Playwright browser automation). Never auto-posts.

**Operations** -- Budget rails enforce per-batch and weekly spend caps. Watch-folder workflow: move a YAML from `drafts/` to `approved/` and cron does the rest.

## Quick Start

```bash
# Clone and install
git clone https://github.com/YOUR_USERNAME/broadside.git
cd broadside
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

# Set up API keys (see External Services below)
# Add keys to ~/.zshenv or .env in the project directory

# Run the guided setup
broadside onboard

# Scout today's news
broadside scout

# Write jokes for a story
broadside write <story-url>

# Render an approved episode
broadside render episodes/approved/ep01.yaml

# Assemble the final video
broadside assemble episodes/approved/ep01.yaml

# Publish (human-initiated, always requires confirmation)
broadside publish ep01 --platform youtube
```

## CLI Commands

```
broadside scout [--dry-run]                          # Pull and rank news stories
broadside write <story> [--batch]                    # LLM comedy writing pipeline
broadside illustrate <episode.yaml>                  # Generate editorial illustrations
broadside ad <concept.yaml> [--random]               # Generate parody ad video
broadside render <episode.yaml> [--dry-run] [--yes]  # Render scenes via HeyGen
broadside assemble <episode.yaml> [--engine auto|ffmpeg|descript]
broadside publish <episode> --platform youtube,x,instagram,tiktok
broadside run [--dry-run] [--yes]                    # Full pipeline (approved/ --> output)
broadside retry <episode> <scene>                    # Re-render a single scene
broadside auth setup|check|refresh <platform>        # Manage credentials
broadside budget [--history]                         # View spend tracking
broadside install-schedule                           # Install cron/launchd/systemd
broadside onboard                                    # Guided first-time setup
```

## External Services

Broadside integrates with several third-party services. Each is optional depending on which parts of the pipeline you use.

### Required

| Service | Purpose | Auth | Free Tier | Cost Estimate |
|---------|---------|------|-----------|---------------|
| [FFmpeg](https://ffmpeg.org/) | Video assembly, captions, audio normalization | Local binary | Free (open source) | $0 |

Install: `brew install ffmpeg` (macOS) or `apt install ffmpeg` (Linux).

### Content Creation

| Service | Purpose | Auth | Free Tier | Cost Estimate |
|---------|---------|------|-----------|---------------|
| [OpenRouter](https://openrouter.ai) | LLM gateway for comedy writing, political filtering, satire scoring | API key (`OPENROUTER_API_KEY`) | Pay-as-you-go | ~$0.45/episode |
| [Replicate](https://replicate.com) | Image generation (Flux 2 Pro) for editorial illustrations and parody ad product shots; jingle generation (MusicGen) | API key (`REPLICATE_API_TOKEN`) | Pay-as-you-go | ~$0.15/episode |
| [ElevenLabs](https://elevenlabs.io) | Voiceover for parody ads (dramatic announcer voice) | API key (`ELEVENLABS_API_KEY`) | Limited free tier | ~$0.05/ad; $5/mo Starter plan |
| [NewsData.io](https://newsdata.io) | Structured news API with category filtering | API key (`NEWSDATA_API_KEY`) | 500 calls/day | $0 |

No-auth sources (no setup needed): Reddit RSS, Hacker News Firebase API, Google News RSS, UPI Odd News RSS, Ars Technica RSS, The Verge RSS.

### Rendering

| Service | Purpose | Auth | Free Tier | Cost Estimate |
|---------|---------|------|-----------|---------------|
| [HeyGen](https://heygen.com) | AI avatar video generation (per-scene rendering) | API key (`HEYGEN_API_KEY`) | Pay-as-you-go wallet | ~$3.50/episode (Avatar IV, ~60s) |

### Assembly (Optional)

| Service | Purpose | Auth | Free Tier | Cost Estimate |
|---------|---------|------|-----------|---------------|
| [Descript](https://descript.com) | Cloud video assembly, Studio Sound, captions (optional -- FFmpeg handles everything locally) | API token (`DESCRIPT_API_TOKEN`) | Requires paid plan | Plan-based credits |

Descript is optional. FFmpeg provides a fully deterministic local fallback for all assembly operations.

### Publishing

| Service | Purpose | Auth | Free Tier | Setup Complexity |
|---------|---------|------|-----------|-----------------|
| [YouTube](https://console.cloud.google.com) | Video uploads via Data API v3 | OAuth 2.0 (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`) | 6 uploads/day | Low -- self-service, no review needed for personal use |
| [X / Twitter](https://developer.x.com) | Tweet with video via chunked upload | OAuth 1.0a (`TWITTER_API_KEY`, `TWITTER_API_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_SECRET`) | 200 tweets/15min | Low -- free developer account |
| [Instagram](https://instagram.com) | Reel uploads via Playwright browser automation | Browser cookies (`broadside auth setup instagram`) | N/A | Medium -- export cookies from browser |
| [TikTok](https://tiktok.com) | Video uploads via Playwright browser automation | Browser cookies (`broadside auth setup tiktok`) | N/A | Medium -- export cookies from browser |

All publishing is **human-initiated**. Broadside never auto-posts to any platform.

## Environment Variables

Set these in `~/.zshenv`, `~/.bashrc`, or a `.env` file in the project directory:

```bash
# Required for content creation
OPENROUTER_API_KEY=           # openrouter.ai -- LLM access

# Required for rendering
HEYGEN_API_KEY=               # heygen.com -- avatar video generation

# Required for illustrations and parody ads
REPLICATE_API_TOKEN=          # replicate.com -- Flux 2 Pro, MusicGen
ELEVENLABS_API_KEY=           # elevenlabs.io -- parody ad voiceover

# Optional -- assembly
DESCRIPT_API_TOKEN=           # descript.com -- cloud assembly (FFmpeg fallback works without this)

# Optional -- news sourcing
NEWSDATA_API_KEY=             # newsdata.io -- structured news API

# Optional -- publishing (YouTube)
GOOGLE_CLIENT_ID=             # Google Cloud Console
GOOGLE_CLIENT_SECRET=         # Google Cloud Console

# Optional -- publishing (X/Twitter)
TWITTER_API_KEY=              # developer.x.com
TWITTER_API_SECRET=
TWITTER_ACCESS_TOKEN=
TWITTER_ACCESS_SECRET=
```

Instagram and TikTok use browser cookies instead of API keys. Run `broadside auth setup instagram` or `broadside auth setup tiktok` to import cookies.

## Episode Format

Episodes are YAML files describing a sequence of scenes:

```yaml
episode: ep03-digital-water
show: bs
post_day: Thursday
caption_hook: "A startup raised $50M to sell water that remembers computers."
scenes:
  - id: s1
    type: talk
    text: "I'm Benn Stone, and this is your daily BS."
  - id: s2
    type: talk
    text: "A startup called HydroSync just raised fifty million dollars for digitally enhanced water."
    pause_after: 1.0
  - id: s3
    type: talk
    text: "That is an actual product that real humans invested real money in."
    zoom: true
    pause_after: 1.2
  - id: s4
    type: card
    asset: assets/cards/sponsor.png
    duration: 2.0
  - id: s5
    type: talk
    text: "I'm Benn Stone, and that's the BS."
end_card:
  wordmark: assets/brand/wordmark.png
  text: "@thatsthebs"
  duration: 2.0
```

Scene types: `talk` (avatar speaks), `card` (full-screen image), `silent` (freeze-frame), `ad` (parody ad insert).

## Watch Folder Workflow

```
episodes/
  drafts/       # Scripts land here -- NEVER rendered
  approved/     # Move here to approve -- cron renders from this folder
  rendered/     # Completed episodes move here automatically
build/          # Scene MP4s and manifests
out/            # Final videos ready for upload
```

Moving a YAML from `drafts/` to `approved/` is the entire approval workflow.

## Budget Rails

Broadside enforces spend limits to prevent runaway API costs:

- **Interactive mode**: prints estimated cost and asks for confirmation
- **Unattended mode** (`--yes`): enforces hard caps without prompting
  - Per-batch cap: $25 (configurable)
  - Weekly rolling cap: $40 (configurable)
- Over-budget runs exit non-zero with a clear summary
- Spend ledger at `~/.broadside/spend.json` tracks all API costs

## Estimated Costs

| Component | Per Episode | Weekly (5 eps) | Monthly (~22 eps) |
|-----------|------------|----------------|-------------------|
| News sourcing (LLM) | ~$0.03 | ~$0.15 | ~$0.65 |
| Comedy writing (LLM) | ~$0.45 | ~$2.25 | ~$10 |
| Illustrations (Replicate) | ~$0.12 | ~$0.60 | ~$2.60 |
| Parody ads (all services) | ~$0.35 | ~$1.75 | ~$7.70 |
| HeyGen rendering (~60s) | ~$3.50 | ~$17.50 | ~$77 |
| FFmpeg assembly | $0 | $0 | $0 |
| **Total** | **~$4.45** | **~$22.25** | **~$98** |

HeyGen rendering is the dominant cost. Using Avatar III engine reduces it to ~$1-2.50/episode.

## Project Structure

```
broadside/
  broadside/           # Python package
    cli.py             # Click CLI
    config.py          # Pydantic config models
    schema.py          # Episode YAML schema
    llm.py             # OpenRouter LLM client
    budget.py          # Spend tracking and guards
    state.py           # Resumable run state
    scout/             # News sourcing pipeline
    writer/            # 4-pass comedy writing
    illustrate/        # Flux 2 Pro editorial illustrations
    ads/               # Parody ad generation
    render/            # HeyGen v3 scene rendering
    assemble/          # Descript + FFmpeg video assembly
    publish/           # Multi-platform publishing
  config/              # config.yaml, character sheet, political keywords
  episodes/            # drafts/, approved/, rendered/
  ads/concepts/        # Parody ad concept YAMLs
  assets/              # Brand assets, cards, fonts, style references
  tests/               # Test suite
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Verify all credentials
broadside auth check
```

## Safety Rails

Broadside will never:

- Generate or alter joke text without human review
- Auto-post to any social platform (publishing always requires confirmation)
- Spend API credits without budget enforcement
- Render anything from the `drafts/` folder
- Write API keys to disk, logs, or git

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for details.
