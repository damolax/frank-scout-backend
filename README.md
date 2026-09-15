# Author Letter Desk — Free Research Backend Edition

A deliberately simple author-research and outreach tool:

**Research → ChatGPT → Import Messages → Send**

There is no paid AI API, no Telegram bot, no browser extension, and no database requirement.

## What works

### 1. Automatic discovery
On the Research screen, enter country/region, genre, preference, target count, and requirements, then choose **Find authors automatically**.

The backend uses public web search to surface likely author sites and adds candidates to the local author list.

### 2. Automatic evidence research
Select authors and choose **Research selected automatically**.

The backend attempts to collect:
- official/likely official website
- public email found on the author's site/contact page
- exact email source page
- books/works from Open Library when available
- short public bio evidence
- recent/current-year activity evidence
- genre hints
- source URLs
- research confidence flags

It does not guess an email or fabricate a book, activity, offer, or personalization claim.

### 3. ChatGPT handoff
Research-ready authors can be exported/copied as a structured ChatGPT prompt. ChatGPT performs the deeper reasoning: what is genuinely relevant to offer, the best personalization angle, subject, and first message.

### 4. Import finished messages
Import CSV, XLSX, or JSON with at least:
- Author
- Email
- Subject
- First Message

Letter Desk matches messages to authors by email first and name second.

### 5. Send one by one
The Send screen provides Copy Subject, Copy Message, Open Email, Mark Sent & Next, Skip, Previous, and Next.

## Data storage

Author and message records are stored in the browser's `localStorage`. This is intentional: Render's free web service does not provide a free persistent disk, and Letter Desk does not need a server database for this workflow.

Use **Backup** in the app regularly to download a JSON backup.

## Free backend stack

- FastAPI
- DDGS public metasearch package
- HTTPX + BeautifulSoup for public page extraction
- Open Library's public search endpoint for book evidence
- Browser localStorage for app data

No secret keys are required.

## Deploy to Render for $0

1. Put all files in a GitHub repository.
2. Sign in to Render.
3. Choose **New → Blueprint** and connect the repository containing `render.yaml`.
   - Or choose **New → Web Service** and connect the repo manually.
4. Select the **Free** compute plan if Render asks.
5. Render uses:
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
   - Health check: `/api/health`
6. Open the generated `https://...onrender.com` URL. The frontend and backend are served from the same service.

No environment variables are required.

## Render Free limitation

The free service can sleep after inactivity. The first research request after a long idle period can therefore be slow while the service wakes up. This does not consume paid API tokens.

## Responsible research behavior

The backend is intentionally conservative:
- checks public pages only
- rejects local/private network targets
- respects `robots.txt` when it can be read
- limits batch sizes and request timeouts
- does not bypass logins/paywalls
- does not guess email addresses
- records sources for important research evidence

Search providers can rate-limit free metasearch traffic. If a research run fails, retry later or use the built-in ChatGPT/manual search fallback.

## Project files

- `index.html` — simplified app UI
- `styles.css` — interface styles
- `app.js` — local workflow + research API integration
- `backend/main.py` — free research backend
- `requirements.txt` — Python dependencies
- `render.yaml` — one-click Render service definition
- `service-worker.js` — frontend offline cache
- `manifest.webmanifest` — app metadata
