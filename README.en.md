**English** | [한국어](README.md)

# Paper Reader

A **local web reader for research papers**. Open a PDF and get translation, figure explanations, smart citations, summaries and Q&A on one screen, using your own AI account or API key. Everything is stored on your machine.

## Features

| Feature | What it does |
|---|---|
| Side-by-side translation | The original PDF stays on the left; **sentence-level translation** appears in a right-hand panel and **scrolls in sync**. Hover a translated sentence to highlight the matching sentence in the PDF, and the other way round. Click a translated sentence to jump to its place in the PDF. |
| Overlay translation | Draws the translation of each paragraph, heading and caption over the original PDF, keeping the layout. |
| Figure and table explanation | Hover a figure or table and click `Explain figure`. The image, its caption and the page text are sent to a vision model. |
| Selection and right-click menu | Select text for an Explain / Translate / Equation / Ask / Highlight toolbar. Right-click for the same menu plus a **question box**. |
| Smart citations | Click an in-text citation (superscript, `[12]`, `(3–5)`, author-year) to see the reference entry and CrossRef metadata (DOI, citation count, abstract), and ask why the authors cite it. |
| Summary and chat | A structured summary of the whole paper, and Q&A grounded in the full text with page references. Conversations are saved. Pick the model and reasoning effort (fast / normal / deep) per request. |
| Notes and library | Translucent highlights with notes, PDF upload and delete. Translations and summaries are cached for instant reuse. |
| Token usage | Today's and this paper's token totals appear in the top bar; hover for a breakdown by task and model. |

## Quick start

Requirements: **Python 3.11+**, **Node.js 18+**

```bash
git clone https://github.com/yzyzero0098/paper-reader.git
cd paper-reader
pip install -r backend/requirements.txt
```

| OS | Run |
|---|---|
| Windows | `start.bat` |
| macOS / Linux | `bash start.sh` |

On first run the frontend is built automatically and http://localhost:8000 opens. Then connect an AI in the settings (⚙, top right).

Development mode with hot reload: `dev.bat` (backend on 8000, Vite on 5173).

## Connecting an AI

Connect at least one provider in the settings. You can choose a default AI and a separate vision model for figure explanations.

| Provider | Authentication | Notes |
|---|---|---|
| **ChatGPT account** | Browser sign-in (OpenAI *Sign in with ChatGPT*) | Runs on your **ChatGPT Plus/Pro subscription** usage, no API key |
| Claude (Anthropic) | API key | Vision supported |
| OpenAI (GPT) | API key | Vision supported |
| Google Gemini | API key | Vision supported |
| DeepSeek | API key | Text only (figure explanation falls back to a vision model) |
| OpenAI-compatible | Base URL (+ key) | Ollama, LM Studio, OpenRouter, etc. |

Keys are stored only in `data/settings.json`. Environment variables (see `.env.example`) are used automatically when no key is saved.

### Sign in with ChatGPT (subscription usage)

Click "Sign in with ChatGPT" in the settings, then approve the app name and "ChatGPT plan usage" on the OpenAI page. The tokens are stored only in `data/chatgpt_auth.json` and refreshed automatically every hour (sign in again if unused for 30+ days). Set per-app usage limits at [ChatGPT settings → Usage](https://chatgpt.com/settings/usage).

- OpenAI's feature is intended for **local and open-source apps** and is still in preview. This project follows the local-app flow in the [official documentation](https://developers.openai.com/siwc/token-sharing-open-source). Running it as a remotely hosted multi-user service needs a separate application to OpenAI and is not supported here.
- Using Claude Pro/Max subscription tokens in third-party apps is prohibited by Anthropic's terms, and Gemini has no official path for subscription access, so neither is implemented. Use API keys for those.

## Docker

```bash
docker compose up -d --build      # http://localhost:8000
```

- Data lives in the `paper-reader-data` volume (`/data`).
- Ports are published on `127.0.0.1` only. The app has no login of its own, so **do not expose it directly to the internet.**
- Pass API keys through shell environment variables or a `.env` file (see `.env.example`).
- The compose file also publishes the callback port (1455) so ChatGPT sign-in works from the container.

## Privacy and caveats

- The paper text (the whole text for summaries and chat) is **sent to the AI provider you choose**. For manuscripts that must stay confidential, use a local model (Ollama) or a provider you are allowed to use.
- Translations, summaries and explanations are AI output and can be wrong. Check important numbers and conclusions against the original.
- There are no user accounts. The app is designed for one person on one computer.

## Layout

```
backend/app/
  main.py          FastAPI routes (REST + SSE streaming); serves the built frontend
  pdf_engine.py    PyMuPDF: text blocks, sentence positions, figure/table regions, citation markers, reference section
  citations.py     Reference parsing + CrossRef lookup
  services.py      Prompts for translation, explanation, summary, chat; caching; token usage logging
  chatgpt_auth.py  Sign in with ChatGPT (PKCE, loopback callback, token refresh and revocation)
  llm/             Provider abstraction (chatgpt, anthropic, openai-compatible, gemini)
  config.py, db.py Settings (settings.json), SQLite (papers, cache, chats, highlights, usage)
backend/scripts/   Developer scripts to inspect layout and citation extraction
frontend/src/      React + Vite (pages/Reader, components/PageView, SidePanel, SettingsModal)
data/              (created at runtime) papers/*.pdf, paper_reader.sqlite, settings.json, chatgpt_auth.json
```

## Known limitations

- Layout extraction is a PyMuPDF heuristic. Scanned PDFs (images only) are not supported.
- Complex multi-panel figures may be merged into one region or split.
- Overlay mode shrinks the font when the translation is much longer than the original.
- Reference parsing handles numbered and author-year styles, but unusual formats may merge some entries.

## License

[MIT](LICENSE)
