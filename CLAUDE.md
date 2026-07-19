# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository purpose

This repository contains a single Claude Code **Skill** definition, `SKILL.md`, named `ai-news-to-social`. It is not a software project — there is no build, lint, or test tooling. The only artifact is the skill's Markdown/YAML-frontmatter prompt file, which Claude Code loads and follows verbatim when the skill is invoked (`/ai-news-to-social` or equivalent).

Editing this repo means editing the instructions in `SKILL.md` itself — there is no separate implementation to keep in sync.

## What the skill does

Converts one AI-related news source (article, post, newsletter excerpt, or link + quote) into a single JSON file containing ready-to-publish captions for five platforms: Telegram, Instagram, X, VKontakte, and TikTok, plus an image-generation prompt.

Key behavioral rules encoded in the skill (preserve these when editing):

- **Single source only.** If the user supplies multiple sources, the skill must ask them to pick one or process them sequentially — it must not blend sources.
- **No fabrication.** Missing facts are marked with the literal placeholder `[уточнить]` rather than invented. Numbers, dates, quotes, product names, and links must never be made up.
- **Output contract is strict:**
  - One JSON file written to `~/pa-finance/posts`.
  - Filename pattern: `YYYY-MM-DD-news-slug-social-content.json`.
  - No text before or after the JSON inside the file.
  - Top-level schema: optional `source` object (`title`, `url`, `published_at`), `image_prompt` string, and `platforms` object where each platform key (`telegram`, `instagram`, `x`, `vk`, `tiktok`) holds an object with a required `content` string.
- **No side effects beyond file creation** — the skill must not take actions outside preparing this one content file.

## Editorial style ("PA" base style)

Applies across all platforms: warm-but-bold Russian-language voice, direct and professional, opinionated (not just summarizing company hype), sparing sarcasm, correct terminology explained simply, concise captions (cut hard after drafting), 1–3 sentence paragraphs, minimal emoji (0–4 depending on platform), bullets only when they genuinely simplify.

Each platform section in `SKILL.md` (Telegram, Instagram, X, VK, TikTok) specifies its own length target, hashtag policy, emoji count, and structural beats (hook → context/explanation → personal take → CTA, roughly). When modifying platform rules, keep the per-platform divergence intentional — these are tuned to each audience (e.g., VK tolerates a more conversational tone and fewer hashtags than Instagram; X and TikTok are terse/high-energy; Telegram is the longest, hashtag-free format).

## Working in this repo

- There are no commands to build, lint, run, or test — validate changes by re-reading `SKILL.md` for internal consistency (e.g., the worked JSON example at the bottom must still match the schema and per-platform rules described above it).
- Keep the frontmatter (`name`, `description`) accurate to the skill's actual behavior, since `description` is what Claude Code uses to decide when to surface this skill.
