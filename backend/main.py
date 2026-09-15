from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
UA = "AuthorLetterDesk/1.0 (+public research; contact via site owner)"
BLOCKED_HOSTS = {
    "amazon.com", "goodreads.com", "wikipedia.org", "facebook.com", "instagram.com",
    "linkedin.com", "x.com", "twitter.com", "youtube.com", "tiktok.com", "pinterest.com"
}
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)

app = FastAPI(title="Author Letter Desk Research API", version="1.0")

class DiscoveryRequest(BaseModel):
    country: str = ""
    genre: str = ""
    gender: str = "Any"
    count: int = Field(default=10, ge=1, le=40)
    requirements: str = ""

class AuthorSeed(BaseModel):
    name: str
    country: str = ""
    genre: str = ""
    website: str = ""
    email: str = ""

class BatchResearchRequest(BaseModel):
    authors: list[AuthorSeed] = Field(default_factory=list, max_length=20)

@dataclass
class Hit:
    title: str
    url: str
    snippet: str

def clean(v: Any) -> str:
    return str(v or "").strip()

def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""

def blocked_host(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in BLOCKED_HOSTS)

def safe_public_url(url: str) -> bool:
    try:
        p = urlparse(url)
        if p.scheme not in {"http", "https"} or not p.hostname:
            return False
        host = p.hostname.lower()
        if host in {"localhost"} or host.endswith((".local", ".internal")):
            return False
        try:
            ip = ipaddress.ip_address(host)
            return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)
        except ValueError:
            pass
        try:
            for info in socket.getaddrinfo(host, None):
                ip = ipaddress.ip_address(info[4][0])
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    return False
        except OSError:
            return False
        return True
    except Exception:
        return False

def search_web(query: str, limit: int = 10) -> list[Hit]:
    try:
        rows = DDGS().text(query, max_results=max(1, min(limit, 20))) or []
    except Exception as exc:
        raise RuntimeError(f"Public search is temporarily unavailable: {exc}") from exc
    out: list[Hit] = []
    for r in rows:
        url = clean(r.get("href") or r.get("url"))
        if not url or not safe_public_url(url):
            continue
        out.append(Hit(clean(r.get("title")), url, clean(r.get("body") or r.get("snippet"))))
    return out

def likely_official(hit: Hit, name: str = "") -> bool:
    host = host_of(hit.url)
    if not host or blocked_host(host):
        return False
    text = f"{hit.title} {hit.snippet} {host}".lower()
    tokens = [t for t in re.findall(r"[a-z]{3,}", name.lower()) if t not in {"author", "writer"}]
    return not tokens or sum(t in text for t in tokens[:3]) >= min(1, len(tokens))

def candidate_name(title: str) -> str:
    s = re.split(r"\s+[|–—-]\s+", clean(title))[0]
    s = re.sub(r"\b(official\s+site|official\s+website|author|writer|books|home)\b", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" -|–—:")
    if not (3 <= len(s) <= 80) or len(s.split()) > 6:
        return ""
    return s

def fetch_page(url: str) -> dict[str, Any]:
    if not safe_public_url(url):
        return {}
    try:
        with httpx.Client(timeout=9, follow_redirects=True, headers={"User-Agent": UA}) as client:
            r = client.get(url)
            if r.status_code >= 400 or "text/html" not in r.headers.get("content-type", ""):
                return {}
            text = r.text[:1_500_000]
    except Exception:
        return {}
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    visible = " ".join(soup.stripped_strings)[:80_000]
    emails = []
    for e in EMAIL_RE.findall(visible + " " + text):
        e = e.lower().strip(".,;:()[]{}<>")
        if e not in emails and not e.endswith(("@example.com", "@sentry.io")):
            emails.append(e)
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        label = (a.get_text(" ", strip=True) + " " + a["href"]).lower()
        if any(k in label for k in ("contact", "about", "bio", "press", "media")):
            u = urljoin(str(r.url), a["href"])
            if safe_public_url(u) and host_of(u) == host_of(str(r.url)) and u not in links:
                links.append(u)
    desc = ""
    meta = soup.find("meta", attrs={"name": re.compile("description", re.I)})
    if meta and meta.get("content"):
        desc = clean(meta.get("content"))
    if not desc:
        p = soup.find("p")
        desc = clean(p.get_text(" ", strip=True) if p else "")[:500]
    return {"url": str(r.url), "text": visible, "emails": emails[:8], "links": links[:8], "description": desc}

def choose_site(name: str, supplied: str = "") -> tuple[str, list[Hit]]:
    if supplied and safe_public_url(supplied):
        return supplied, []
    hits = search_web(f'"{name}" author official website', 10)
    for h in hits:
        if likely_official(h, name):
            return h.url, hits
    return "", hits

def book_evidence(name: str) -> tuple[str, str]:
    try:
        with httpx.Client(timeout=8, headers={"User-Agent": UA}) as client:
            r = client.get("https://openlibrary.org/search.json", params={"author": name, "limit": 8, "fields": "title,author_name,first_publish_year"})
            r.raise_for_status()
            docs = r.json().get("docs", [])
        titles = []
        for d in docs:
            t = clean(d.get("title"))
            if t and t not in titles:
                titles.append(t)
        return "; ".join(titles[:6]), f"https://openlibrary.org/search?q={httpx.QueryParams({'author': name})['author']}"
    except Exception:
        return "", ""

def research_author(seed: AuthorSeed) -> dict[str, Any]:
    name = clean(seed.name)
    if not name:
        raise ValueError("Author name is required")
    website, site_hits = choose_site(name, clean(seed.website))
    pages: list[dict[str, Any]] = []
    if website:
        home = fetch_page(website)
        if home:
            pages.append(home)
            for u in home.get("links", [])[:3]:
                p = fetch_page(u)
                if p:
                    pages.append(p)
    emails: list[tuple[str, str]] = []
    for p in pages:
        for e in p.get("emails", []):
            if not any(x[0] == e for x in emails):
                emails.append((e, p.get("url", website)))
    email = clean(seed.email) or (emails[0][0] if emails else "")
    email_source = next((u for e, u in emails if e == email), "")
    books, book_source = book_evidence(name)
    activity_hits = search_web(f'"{name}" author 2026 interview event new book', 5)
    activity = activity_hits[0].snippet[:500] if activity_hits else ""
    activity_source = activity_hits[0].url if activity_hits else ""
    bio = next((p.get("description", "") for p in pages if p.get("description")), "")
    genre = clean(seed.genre)
    if not genre:
        g_hits = search_web(f'"{name}" author genre', 4)
        if g_hits:
            genre = g_hits[0].snippet[:240]
    sources = []
    for u in [website, email_source, book_source, activity_source] + [h.url for h in site_hits[:3]]:
        if u and u not in sources:
            sources.append(u)
    return {"name": name, "country": clean(seed.country), "website": website, "email": email, "emailSource": email_source, "genre": genre, "books": books, "bio": bio, "activity": activity, "hook": "", "offer": "", "notes": "\n".join(sources)}

def discover(req: DiscoveryRequest) -> list[dict[str, Any]]:
    terms = [req.country, req.genre, "author", "official website"]
    if req.gender and req.gender != "Any":
        terms.insert(0, req.gender.split()[0])
    hits = search_web(" ".join(t for t in terms if clean(t)), min(20, max(req.count * 2, 10)))
    found: list[dict[str, Any]] = []
    seen_hosts: set[str] = set()
    for h in hits:
        host = host_of(h.url)
        if not host or host in seen_hosts or blocked_host(host):
            continue
        name = candidate_name(h.title)
        if not name or not likely_official(h, name):
            continue
        seen_hosts.add(host)
        page = fetch_page(h.url)
        email = page.get("emails", [""])[0] if page else ""
        found.append({"name": name, "country": clean(req.country), "website": page.get("url", h.url) if page else h.url, "email": email, "emailSource": page.get("url", h.url) if email else "", "genre": clean(req.genre), "books": "", "bio": page.get("description", "") if page else h.snippet[:500], "activity": "", "hook": "", "offer": "", "notes": h.url})
        if len(found) >= req.count:
            break
    return found

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "author-letter-desk", "paid_api": False}

@app.post("/api/discover")
def api_discover(req: DiscoveryRequest) -> dict[str, Any]:
    try:
        authors = discover(req)
        return {"count": len(authors), "authors": authors}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@app.post("/api/research")
def api_research(seed: AuthorSeed) -> dict[str, Any]:
    try:
        return research_author(seed)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@app.post("/api/research-batch")
async def api_research_batch(req: BatchResearchRequest) -> dict[str, Any]:
    sem = asyncio.Semaphore(3)
    async def one(seed: AuthorSeed):
        async with sem:
            try:
                result = await asyncio.to_thread(research_author, seed)
                return result, None
            except Exception as exc:
                return None, {"name": seed.name, "error": str(exc)}
    results = await asyncio.gather(*(one(a) for a in req.authors))
    return {"authors": [a for a, _ in results if a], "errors": [e for _, e in results if e]}

PUBLIC = {"index.html": "text/html", "styles.css": "text/css", "app.js": "application/javascript", "manifest.webmanifest": "application/manifest+json", "service-worker.js": "application/javascript"}

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "index.html")

@app.get("/{name}", include_in_schema=False)
def public_file(name: str):
    if name not in PUBLIC:
        raise HTTPException(status_code=404)
    return FileResponse(ROOT / name, media_type=PUBLIC[name])
