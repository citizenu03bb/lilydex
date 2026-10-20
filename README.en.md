# Lilydex — English overview

Lilydex digitises, identifies, prices and sells a multilingual Pokémon card collection
(French, English, Japanese and Italian cards). The shop is live:
[lilydex.duckdns.org](https://lilydex.duckdns.org). The Python package and its commands are
called `pokeprice`, `pokeprice-manage` and `pokeprice-agent`.

The interface and the detailed documentation are in French; this page summarises the project
for non-French readers. The [French README](README.md) is the reference.

## What it does

- **Scan binders** (`pokeprice` command line). Photograph each page; the command slices the
  pockets, reads each card and matches it against the open [TCGdex](https://tcgdex.dev)
  catalogue, with Cardmarket (€) and TCGplayer ($) prices. Reading is local by default (Gemma
  through Ollama) or, optionally, done by Gemini in the cloud.
- **Manage the collection** (private web app, `/gestion`), from an Android phone or a computer:
  one record per physical copy with its own photos, a full history of corrections, variants,
  dated price snapshots, lots and sales.
- **Sell** (public storefront at the site root): published cards are browsable without an
  account; a registered customer, approved by an administrator, requests a reservation, which
  becomes a lot.
- **Delegate to an agent**: an AI agent can work on one album with its own revocable key; it
  only prepares draft lots, and a person publishes, reserves and sells.

## AI and vision: models propose, a person decides

Every model output is a *proposal* stored with its evidence (photo, model, protocol, raw
answer). A person confirms identity, variant and condition; no reading ever changes a record.
Models abstain when unsure, and every choice was measured on a bench of hand-verified cards.

| Component | Model | Runs on | Measured |
|---|---|---|---|
| Card reading at intake | Gemini (vision-language) | cloud, called by the server | collector number right 23 to 25 times out of 30 depending on the run; language 30/30 |
| Finish, stamp and text language | Gemini | cloud, after each intake | holo vs flat: no error on 21 cards when the reading decides; language 31/31, no false alarm; no unsafe variant proposal above the value threshold |
| Image edition check | DINOv2-small, pre-trained | ARM server, CPU only | 22 of 27 true editions confirmed, one false alarm |
| Energy gate (command line) | DINOv2-small, nearest neighbours with rejection | laptop or server | 166/166 basic Energy cards admitted, one other card wrongly admitted out of 1,601 |
| Photo preparation | classic computer vision (Pillow), no AI | server | not measured; the original is always kept |
| Condition help | Gemini | cloud, on demand only | not measured: a proposal, never a grade |

*Measurement conditions: 31 cards from a single collection checked against the physical cards (25 FR, 5 EN, 1 IT, no Japanese; 21 with a verified variant, 2 of them reverse holos), gemini-3.8-flash and DINOv2-small, bench replayed through the app, two runs judged on the worse; energy gate: 1,767 copies, each card left out of its own bank; October 2026. Bench data is private, so these figures cannot be replayed from the repository alone.*

Engineering choices, each backed by a measurement and written up as a decision record (in
French, [docs/decisions/](docs/decisions/README.md)):

- **Tesseract rejected** as a language checker: 28/31 right, 3 false alarms, and it caught none
  of Gemini's errors. A consistency check inside the existing Gemini reading replaced it.
- **DINOv2 over CLIP** (19/27 vs 13/27 top-1), with an abstention margin of 0.05 chosen from a
  trade-off table (0.02: 3 false alarms; 0.08: 11 instead of 14 near-miss editions caught).
- **Comfort thresholds vs safety thresholds**: number and edition floors follow the observed
  noise, but thresholds that keep a valuable card from being sold as bulk are never lowered.
- **Reverse holos are checked by hand** above the value threshold: no model tested spots them
  reliably on a binder photo.
- **CPU-only torch on the ARM server**: no GPU, so no multi-gigabyte CUDA libraries; memory and
  disk footprint measured.

What the AI does **not** do: it confirms nothing, does not reliably detect reverse holos, does
not flag counterfeits, does not grade condition, and no model is trained or fine-tuned.

## Under the hood

- **App**: FastAPI and SQLite; plain HTML, CSS and JavaScript with no external dependency;
  admin, editor and reader roles plus storefront customers.
- **Hosting**: Oracle Cloud free tier (ARM), Caddy with Let's Encrypt, hardened systemd unit
  (dedicated user, read-only system, hidden home directories, no privilege escalation).
- **Backups**: nightly archive verified by a test restore on the server; the laptop pulls it,
  encrypts it with age and uploads it to Google Drive, then downloads and restores it again.
  The server never holds a Drive token.
- **Security and privacy**: pre-publication security audit, GDPR register, API keys kept
  server-side, scrypt password hashing, strict same-site cookies and origin checks.
- **Quality**: Python and JavaScript (Node.js) tests with injected fakes for every model and
  service, a recognition bench used as a non-regression test, and an automated documentation
  check (links, dates, private patterns).

## Try it

```bash
git clone https://github.com/citizenu03bb/lilydex.git && cd lilydex
uv sync --extra web
uv run --extra web pokeprice-manage serve
```

Open <http://127.0.0.1:3820/gestion> and create the administrator account. Card reading needs a
`GEMINI_API_KEY` in `~/.env`; without it, enter cards by hand. Add `--extra vision` for the
image edition check.

## How it is built

Lilydex is developed with coding agents, mostly Claude Code; most commits carry a
`Co-Authored-By` trailer. The maintainer sets milestones and exit criteria, establishes ground
truth on the physical cards, decides in writing and reviews; the bench and the tests act as
guardrails. Coding agents were themselves measured on the bench as card readers and were not
retained.

## Limits

- One collection per installation; hosting several collections is under study.
- Interface internationalisation and an installable web app (PWA) are planned, not built.
- Measurements cover 21 to 31 cards from one collection, with no Japanese card.
- Maintained by one person, with no guaranteed response time.

## Licence

MIT. Pokémon names, images and trademarks belong to their owners; catalogue and price data come
from [TCGdex](https://tcgdex.dev) and Cardmarket. To report a vulnerability, see
[SECURITY.md](SECURITY.md).
