"""
YT Clean Proxy — Python backend (Railway / Render / Fly / Docker / VPS)
v2.0 — Fixes: cookie validation, single-stream formats, URL caching, better errors
"""

import asyncio
import hashlib
import os
import time
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, field_validator

app = FastAPI(title="YT Clean Proxy", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

links: dict[str, dict] = {}
rate_limits: dict[str, list[float]] = defaultdict(list)

RATE_LIMIT = int(os.getenv("RATE_LIMIT", "15"))
COOKIES_PATH = os.getenv("COOKIES_PATH", "/app/cookies.txt")

# URL cache: short_id -> { direct_url, headers, fetched_at }
# Avoids re-running yt-dlp on every stream request (URLs are valid ~6h)
_url_cache: dict[str, dict] = {}
URL_CACHE_TTL = 60 * 60 * 5  # 5 hours


QualityType = Literal["360", "480", "720", "1080", "best"]

# Use formats that guarantee a single streamable file (no separate A+V merge needed)
# bestvideo+bestaudio requires ffmpeg merging — not suitable for HTTP streaming
# We pick best single-file format at the given height cap
QUALITY_FORMATS: dict[str, str] = {
    "360":  "best[height<=360][ext=mp4]/best[height<=360]/worst[ext=mp4]",
    "480":  "best[height<=480][ext=mp4]/best[height<=480]/best[ext=mp4]",
    "720":  "best[height<=720][ext=mp4]/best[height<=720]/best[ext=mp4]",
    "1080": "best[height<=1080][ext=mp4]/best[height<=1080]/best[ext=mp4]",
    "best": "best[ext=mp4]/best",
}

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)


class GenerateRequest(BaseModel):
    url: str
    expire_minutes: int = 30
    quality: QualityType = "best"

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if "youtube.com/" not in v and "youtu.be/" not in v:
            raise ValueError("Must be a YouTube URL (youtube.com or youtu.be)")
        if len(v) > 500:
            raise ValueError("URL too long")
        return v

    @field_validator("expire_minutes")
    @classmethod
    def validate_expire(cls, v: int) -> int:
        if v not in (0, 5, 30, 60, 1440):
            raise ValueError("expire_minutes must be 0, 5, 30, 60, or 1440")
        return v


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(ip: str) -> None:
    now = time.time()
    rate_limits[ip] = [t for t in rate_limits[ip] if now - t < 60]
    if len(rate_limits[ip]) >= RATE_LIMIT:
        raise HTTPException(429, "Rate limit exceeded — try again in a minute.")
    rate_limits[ip].append(now)


def generate_short_id(url: str) -> str:
    h = hashlib.sha256(f"{url}{time.time()}".encode()).hexdigest()
    return h[:8]


def _build_yt_cmd(url: str, quality: str, dump_json: bool = True) -> list[str]:
    fmt = QUALITY_FORMATS.get(quality, QUALITY_FORMATS["best"])
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        "-f", fmt,
        "--extractor-args", "youtube:player_client=web,android,ios",
        "--geo-bypass",
        "--user-agent", _USER_AGENT,
        "--referer", "https://www.youtube.com/",
        "--socket-timeout", "30",
    ]
    if dump_json:
        cmd.append("-j")
    if os.path.isfile(COOKIES_PATH):
        cmd.extend(["--cookies", COOKIES_PATH])
    cmd.append(url)
    return cmd


def _classify_error(stderr: str) -> str:
    s = stderr.lower()
    if "sign in" in s or "bot" in s or "confirm you're not a bot" in s or "please sign in" in s:
        return (
            "YouTube blocked this request (anti-bot / age-gate). "
            "Upload a fresh cookies.txt from a logged-in Chrome session "
            "(export while on the video page, not the feed). "
            "See Settings > Upload Cookies."
        )
    if "private video" in s:
        return "This video is private."
    if "copyright" in s or "not available" in s:
        return "This video is unavailable in your region or has been removed."
    if "members only" in s or "membership" in s:
        return "This video requires a YouTube channel membership."
    if "live" in s and "not" not in s:
        return "Live streams cannot be downloaded — wait until the stream ends."
    if "429" in s or "too many requests" in s:
        return (
            "YouTube is rate-limiting this server. "
            "Wait a few minutes or upload cookies to reduce bot detection."
        )
    return f"yt-dlp error: {stderr[:300]}"


def get_yt_info(url: str, quality: str = "best") -> dict:
    cmd = _build_yt_cmd(url, quality, dump_json=True)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "yt-dlp timed out (90s). The video may be too long or the server is busy.")

    if result.returncode != 0:
        raise HTTPException(
            403 if ("sign in" in result.stderr.lower() or "bot" in result.stderr.lower()) else 500,
            _classify_error(result.stderr)
        )

    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise HTTPException(500, "yt-dlp returned unexpected output — try again.")

    direct_url = info.get("url")
    if not direct_url:
        raise HTTPException(500, "yt-dlp did not return a direct URL. The video format may be unsupported.")

    return {
        "title": info.get("title", "video"),
        "direct_url": direct_url,
        "http_headers": info.get("http_headers", {}),
        "height": info.get("height"),
        "format_note": info.get("format_note", ""),
        "ext": info.get("ext", "mp4"),
    }


def get_yt_info_cached(short_id: str, youtube_url: str, quality: str) -> dict:
    """Return cached URL info, refreshing if stale."""
    now = time.time()
    cached = _url_cache.get(short_id)
    if cached and (now - cached["fetched_at"]) < URL_CACHE_TTL:
        return cached

    info = get_yt_info(youtube_url, quality)
    _url_cache[short_id] = {**info, "fetched_at": now}
    return _url_cache[short_id]


def cleanup_expired() -> None:
    now = datetime.now(timezone.utc)
    expired = [k for k, v in list(links.items()) if v.get("expires_at") and v["expires_at"] < now]
    for k in expired:
        links.pop(k, None)
        _url_cache.pop(k, None)


# ===========================
#  ROUTES
# ===========================

@app.get("/")
async def health() -> dict:
    cookies_ok = os.path.isfile(COOKIES_PATH)
    cookies_lines = 0
    if cookies_ok:
        try:
            with open(COOKIES_PATH) as f:
                cookies_lines = sum(1 for l in f if l.strip() and not l.startswith("#"))
        except Exception:
            pass
    return {
        "status": "ok",
        "service": "YT Clean Proxy",
        "version": "2.0.0",
        "cookies_configured": cookies_ok,
        "cookies_entries": cookies_lines,
        "active_links": len(links),
    }


@app.post("/upload-cookies")
async def upload_cookies(file: UploadFile = File(...)) -> dict:
    content = await file.read()
    text = content.decode("utf-8", errors="replace")

    # Validate Netscape cookie format
    if "HTTP Cookie File" not in text and ".youtube.com" not in text and "youtube.com" not in text:
        raise HTTPException(
            400,
            "File does not look like a valid YouTube cookies.txt. "
            "Export using the 'Get cookies.txt LOCALLY' Chrome extension while on youtube.com."
        )

    os.makedirs(os.path.dirname(COOKIES_PATH) or ".", exist_ok=True)
    with open(COOKIES_PATH, "wb") as f:
        f.write(content)

    entry_count = sum(1 for l in text.splitlines() if l.strip() and not l.startswith("#"))
    return {"status": "ok", "message": f"Cookies uploaded successfully ({entry_count} entries)."}


@app.delete("/cookies")
async def delete_cookies() -> dict:
    if os.path.isfile(COOKIES_PATH):
        os.remove(COOKIES_PATH)
    _url_cache.clear()
    return {"status": "ok", "message": "Cookies deleted."}


@app.post("/generate")
async def generate(req: GenerateRequest, request: Request) -> dict:
    ip = get_client_ip(request)
    check_rate_limit(ip)
    cleanup_expired()

    try:
        info = await asyncio.to_thread(get_yt_info, req.url, req.quality)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

    short_id = generate_short_id(req.url)

    # Cache the URL so the stream endpoint doesn't need another yt-dlp call immediately
    _url_cache[short_id] = {**info, "fetched_at": time.time()}

    expires_at = None
    if req.expire_minutes > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=req.expire_minutes)

    base_url = os.getenv("BASE_URL", str(request.base_url).rstrip("/"))

    links[short_id] = {
        "youtube_url": req.url,
        "title": info["title"],
        "expires_at": expires_at,
        "quality": req.quality,
    }

    clean_url = f"{base_url}/v/{short_id}.mp4"

    if req.expire_minutes == 0:
        expires_label = "Never expires"
    elif req.expire_minutes < 60:
        expires_label = f"{req.expire_minutes} min"
    elif req.expire_minutes == 60:
        expires_label = "1 hour"
    else:
        h = req.expire_minutes // 60
        expires_label = f"{h} hours"

    if info.get("height"):
        quality_label = f"{info['height']}p"
    elif req.quality == "best":
        quality_label = "Best"
    else:
        quality_label = f"{req.quality}p"

    return {
        "clean_url": clean_url,
        "expires_in": expires_label,
        "quality": quality_label,
        "title": f"{info['title']}.mp4",
    }


@app.get("/v/{short_id}.mp4")
async def stream_video(short_id: str, request: Request) -> StreamingResponse:
    cleanup_expired()

    entry = links.get(short_id)
    if not entry:
        raise HTTPException(410, "Link expired or not found.")

    if entry.get("expires_at") and entry["expires_at"] < datetime.now(timezone.utc):
        links.pop(short_id, None)
        _url_cache.pop(short_id, None)
        raise HTTPException(410, "This link has expired.")

    try:
        info = await asyncio.to_thread(
            get_yt_info_cached,
            short_id,
            entry["youtube_url"],
            entry.get("quality", "best"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Failed to resolve video URL: {e}")

    direct_url = info["direct_url"]

    req_headers: dict[str, str] = {
        k: v for k, v in info.get("http_headers", {}).items()
        if k.lower() not in ("host",)
    }
    req_headers.setdefault("User-Agent", _USER_AGENT)
    req_headers.setdefault("Referer", "https://www.youtube.com/")

    range_header = request.headers.get("range")
    if range_header:
        req_headers["Range"] = range_header

    safe_title = entry["title"].replace('"', "'").replace("\n", " ")

    client = httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30.0, read=None))

    try:
        req_obj = client.build_request("GET", direct_url, headers=req_headers)
        source_resp = await client.send(req_obj, stream=True)

        if source_resp.status_code == 403:
            await client.aclose()
            # Invalidate cache so next request gets a fresh URL
            _url_cache.pop(short_id, None)
            raise HTTPException(
                502,
                "The video URL expired (YouTube CDN 403). "
                "Click 'Generate' again to get a fresh link."
            )

        async def stream_generator():
            try:
                async for chunk in source_resp.aiter_bytes(65536):
                    yield chunk
            finally:
                await source_resp.aclose()
                await client.aclose()

        resp_headers: dict[str, str] = {
            "Content-Type": "video/mp4",
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'inline; filename="{safe_title}.mp4"',
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges",
        }

        if "content-range" in source_resp.headers:
            resp_headers["Content-Range"] = source_resp.headers["content-range"]
        if "content-length" in source_resp.headers:
            resp_headers["Content-Length"] = source_resp.headers["content-length"]

        status = source_resp.status_code
        # Treat 200 for range requests as 206
        if range_header and status == 200:
            status = 206

        return StreamingResponse(
            stream_generator(),
            status_code=status,
            headers=resp_headers,
        )

    except HTTPException:
        await client.aclose()
        raise
    except Exception as e:
        await client.aclose()
        raise HTTPException(502, f"Failed to stream video: {e}")
