"""
YT Clean Proxy — Python backend (Railway / Render / Fly / Docker / VPS)
"""

import asyncio
import hashlib
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

app = FastAPI(title="YT Clean Proxy", version="1.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

links: dict[str, dict] = {}
rate_limits: dict[str, list[float]] = defaultdict(list)

RATE_LIMIT = 10
COOKIES_PATH = os.getenv("COOKIES_PATH", "/app/cookies.txt")

QualityType = Literal["360", "480", "720", "1080", "best"]

# Map quality -> yt-dlp format string. Falls back gracefully.
QUALITY_FORMATS: dict[str, str] = {
    "360": "best[height<=360]/bv*[height<=360]+ba/best[height<=360]",
    "480": "best[height<=480]/bv*[height<=480]+ba/best[height<=480]",
    "720": "best[height<=720]/bv*[height<=720]+ba/best[height<=720]",
    "1080": "best[height<=1080]/bv*[height<=1080]+ba/best[height<=1080]",
    "best": "best[ext=mp4]/bv*+ba/best",
}


class GenerateRequest(BaseModel):
    url: str
    expire_minutes: int = 30
    quality: QualityType = "best"

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        if "youtube.com/" not in v and "youtu.be/" not in v:
            raise ValueError("Must be a valid YouTube URL")
        if len(v) > 500:
            raise ValueError("URL too long")
        return v

    @field_validator("expire_minutes")
    @classmethod
    def validate_expire(cls, v):
        if v not in (0, 5, 30, 60, 1440):
            raise ValueError("expire_minutes must be 0, 5, 30, 60, or 1440")
        return v


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(ip: str):
    now = time.time()
    rate_limits[ip] = [t for t in rate_limits[ip] if now - t < 60]
    if len(rate_limits[ip]) >= RATE_LIMIT:
        raise HTTPException(429, "Rate limit exceeded. Try again in a minute.")
    rate_limits[ip].append(now)


def generate_short_id(url: str) -> str:
    h = hashlib.sha256(f"{url}{time.time()}".encode()).hexdigest()
    return h[:8]


def get_yt_info(url: str, quality: str = "best") -> dict:
    import json
    import subprocess

    fmt = QUALITY_FORMATS.get(quality, QUALITY_FORMATS["best"])

    cmd = [
        "yt-dlp",
        "--no-warnings",
        "-j",
        "-f", fmt,
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--extractor-args", "youtube:player_client=web,android,ios",   
        "--geo-bypass",
        "--user-agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",          
        "--referer", "https://www.youtube.com/",
    ]
    if os.path.isfile(COOKIES_PATH):
        cmd.extend(["--cookies", COOKIES_PATH])
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        err = result.stderr.strip()
        if "Sign in" in err or "bot" in err.lower() or "confirm you're not a bot" in err.lower():
            raise HTTPException(
                403,
                "YouTube blocked this video (anti-bot). "
                "Re-export fresh cookies.txt from Chrome (logged in, on the VIDEO page itself — not just the feed) "
                "or try a different video.",
            )
        raise HTTPException(500, f"yt-dlp error: {err[:300]}")

    info = json.loads(result.stdout)
    return {
        "title": info.get("title", "video"),
        "direct_url": info.get("url"),
        "http_headers": info.get("http_headers", {}),
        "height": info.get("height"),
        "format_note": info.get("format_note", ""),
    }


def cleanup_expired():
    now = datetime.now(timezone.utc)
    expired = [k for k, v in links.items() if v.get("expires_at") and v["expires_at"] < now]
    for k in expired:
        del links[k]


@app.get("/")
async def health():
    return {
        "status": "ok",
        "service": "YT Clean Proxy",
        "version": "1.5.0",
        "mode": "proxy-stream",
        "cookies_configured": os.path.isfile(COOKIES_PATH),
    }


@app.post("/upload-cookies")
async def upload_cookies(file: UploadFile = File(...)):
    content = await file.read()
    os.makedirs(os.path.dirname(COOKIES_PATH) or ".", exist_ok=True)
    with open(COOKIES_PATH, "wb") as f:
        f.write(content)
    return {"status": "ok", "message": "Cookies uploaded successfully."}


@app.post("/generate")
async def generate(req: GenerateRequest, request: Request):
    ip = get_client_ip(request)
    check_rate_limit(ip)
    cleanup_expired()

    info = await asyncio.to_thread(get_yt_info, req.url, req.quality)

    short_id = generate_short_id(req.url)

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

    expires_label = (
        "Never expires" if req.expire_minutes == 0 else
        f"{req.expire_minutes}m" if req.expire_minutes < 60 else
        f"{req.expire_minutes // 60}h" + ("s" if req.expire_minutes // 60 > 1 else "")
    )

    quality_label = (
        f"{info['height']}p" if info.get("height") else
        ("Best" if req.quality == "best" else f"{req.quality}p")
    )

    return {
        "clean_url": clean_url,
        "expires_in": expires_label,
        "quality": quality_label,
        "title": f"{info['title']}.mp4",
    }


# ==================== STREAMING ENDPOINT ====================
@app.get("/v/{short_id}.mp4")
async def stream_video(short_id: str, request: Request):
    cleanup_expired()

    entry = links.get(short_id)
    if not entry:
        raise HTTPException(410, "Link expired or not found")

    if entry.get("expires_at") and entry["expires_at"] < datetime.now(timezone.utc):
        del links[short_id]
        raise HTTPException(410, "Link has expired")

    fresh_info = await asyncio.to_thread(
        get_yt_info, entry["youtube_url"], entry.get("quality", "best")
    )
    direct_url = fresh_info["direct_url"]

    headers = dict(fresh_info.get("http_headers", {}))
    headers.setdefault(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    )
    headers.setdefault("Referer", "https://www.youtube.com/")

    if range_header := request.headers.get("range"):
        headers["Range"] = range_header

    safe_title = entry["title"].replace('"', "'").replace("\n", " ")

    client = httpx.AsyncClient(follow_redirects=True, timeout=None)

    try:
        req_obj = client.build_request("GET", direct_url, headers=headers)
        source_resp = await client.send(req_obj, stream=True)

        async def stream_generator():
            try:
                async for chunk in source_resp.aiter_bytes(65536):
                    yield chunk
            finally:
                await source_resp.aclose()
                await client.aclose()

        resp_headers = {
            "Content-Type": "video/mp4",
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'inline; filename="{safe_title}.mp4"',
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges",
        }

        if "Content-Range" in source_resp.headers:
            resp_headers["Content-Range"] = source_resp.headers["Content-Range"]
        if "Content-Length" in source_resp.headers:
            resp_headers["Content-Length"] = source_resp.headers["Content-Length"]

        return StreamingResponse(
            stream_generator(),
            status_code=source_resp.status_code,
            headers=resp_headers,
        )

    except Exception as e:
        await client.aclose()
        raise HTTPException(502, "Failed to stream video") from e
