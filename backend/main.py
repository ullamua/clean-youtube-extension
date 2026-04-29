"""
YT Clean Proxy — Python backend (Railway / Render / Fly / Docker / VPS)
v2.3 — better YouTube challenge solving, adaptive quality muxing, safer headers
"""

import asyncio
import hashlib
import os
import time
import json
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional
from urllib.parse import quote
import re

import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, field_validator

app = FastAPI(title="YT Clean Proxy", version="2.3.0")

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

# Prefer adaptive MP4 video + M4A audio so 480p/720p/1080p actually work.
# Fall back to a single-file stream when YouTube withholds adaptive MP4 formats.
QUALITY_FORMATS: dict[str, str] = {
    "360": (
        "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/"
        "bestvideo[height<=360][ext=mp4]+bestaudio[acodec^=mp4a]/"
        "best[height<=360][ext=mp4][vcodec!=none][acodec!=none]/"
        "best[height<=360][vcodec!=none][acodec!=none]"
    ),
    "480": (
        "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/"
        "bestvideo[height<=480][ext=mp4]+bestaudio[acodec^=mp4a]/"
        "best[height<=480][ext=mp4][vcodec!=none][acodec!=none]/"
        "best[height<=480][vcodec!=none][acodec!=none]"
    ),
    "720": (
        "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
        "bestvideo[height<=720][ext=mp4]+bestaudio[acodec^=mp4a]/"
        "best[height<=720][ext=mp4][vcodec!=none][acodec!=none]/"
        "best[height<=720][vcodec!=none][acodec!=none]"
    ),
    "1080": (
        "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
        "bestvideo[height<=1080][ext=mp4]+bestaudio[acodec^=mp4a]/"
        "best[height<=1080][ext=mp4][vcodec!=none][acodec!=none]/"
        "best[height<=1080][vcodec!=none][acodec!=none]"
    ),
    "best": (
        "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
        "bestvideo[ext=mp4]+bestaudio[acodec^=mp4a]/"
        "best[ext=mp4][vcodec!=none][acodec!=none]/"
        "best[vcodec!=none][acodec!=none]"
    ),
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


def _ascii_filename(title: str, fallback: str = "video") -> str:
    """Return a header-safe ASCII filename. Starlette encodes headers as latin-1."""
    cleaned = re.sub(r'[^A-Za-z0-9._ -]+', '', title).strip(' ._-')
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return (cleaned or fallback)[:120]


def _content_disposition(title: str, ext: str = "mp4") -> str:
    ascii_name = _ascii_filename(title)
    ext = re.sub(r'[^A-Za-z0-9]+', '', ext or "mp4") or "mp4"
    utf8_name = quote(f"{title}.{ext}", safe="")
    return f'inline; filename="{ascii_name}.{ext}"; filename*=UTF-8\'\'{utf8_name}'


def _build_yt_cmd(
    url: str,
    quality: str,
    dump_json: bool = True,
    *,
    use_cookies: bool = True,
    player_client: Optional[str] = None,
) -> list[str]:
    fmt = QUALITY_FORMATS.get(quality, QUALITY_FORMATS["best"])
    remote_components = os.getenv("YT_REMOTE_COMPONENTS", "ejs:github")
    js_runtime = os.getenv("YT_JS_RUNTIME", "deno")
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        "-f", fmt,
        "--geo-bypass",
        "--force-ipv4",
        "--user-agent", _USER_AGENT,
        "--referer", "https://www.youtube.com/",
        "--socket-timeout", "30",
        "--extractor-args", "youtube:formats=missing_pot",
        "--format-sort", "res,codec:h264,aext:m4a,br",
    ]
    if remote_components:
        cmd.extend(["--remote-components", remote_components])
    if js_runtime:
        cmd.extend(["--js-runtimes", js_runtime])
    if player_client:
        cmd.extend(["--extractor-args", f"youtube:player_client={player_client}"])
    if dump_json:
        cmd.append("-j")
    if use_cookies and os.path.isfile(COOKIES_PATH):
        cmd.extend(["--cookies", COOKIES_PATH])
    cmd.append(url)
    return cmd


def _classify_error(stderr: str) -> str:
    s = stderr.lower()
    if "some formats may be missing" in s or "n challenge solving failed" in s:
        return (
            "YouTube is partially blocking format extraction on this server. "
            "The backend should enable the challenge solver runtime and EJS components; if it still fails, try another server IP."
        )
    if "sign in" in s or "bot" in s or "confirm you're not a bot" in s or "please sign in" in s:
        return (
            "YouTube blocked this request (anti-bot / age-gate). "
            "Try a different server/network IP first. If you use cookies, export them after fully closing YouTube tabs; "
            "some YouTube account sessions are blocked even when the cookie file is fresh."
        )
    if "not available on this app" in s or "content isn't available" in s or "content is not available" in s:
        return (
            "YouTube rejected this player session. This is usually a blocked cookie account/IP, not a real regional block. "
            "The backend tried both authenticated and anonymous fallback clients. Try without cookies or from a different IP."
        )
    if "private video" in s:
        return "This video is private."
    if "copyright" in s or "not available" in s or "region" in s or "country" in s:
        return (
            "YouTube reports this video/account/IP as unavailable. If this happens for every video, "
            "your uploaded cookies or server IP are blocked; delete cookies or use a different backend IP."
        )
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


def _normalize_headers(raw_headers: dict | None) -> dict[str, str]:
    headers = {k: v for k, v in (raw_headers or {}).items() if isinstance(k, str) and isinstance(v, str)}
    headers.pop("Host", None)
    headers.pop("host", None)
    headers.setdefault("User-Agent", _USER_AGENT)
    headers.setdefault("Referer", "https://www.youtube.com/")
    return headers


def _parse_requested_formats(info: dict) -> tuple[Optional[dict], Optional[dict]]:
    requested_formats = info.get("requested_formats") or []
    video = None
    audio = None
    for fmt in requested_formats:
        if not isinstance(fmt, dict):
            continue
        if fmt.get("vcodec") not in (None, "none") and not video:
            video = fmt
        if fmt.get("acodec") not in (None, "none") and not audio:
            audio = fmt
    return video, audio


def _extract_yt_info(url: str, quality: str, *, use_cookies: bool, player_client: Optional[str]) -> tuple[dict, str]:
    cmd = _build_yt_cmd(url, quality, dump_json=True, use_cookies=use_cookies, player_client=player_client)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "yt-dlp timed out (90s). The video may be too long or the server is busy.")

    if result.returncode != 0:
        mode = f"{'cookies' if use_cookies else 'no-cookies'} / {player_client or 'yt-dlp-default'}"
        raise HTTPException(
            403 if ("sign in" in result.stderr.lower() or "bot" in result.stderr.lower()) else 500,
            f"{_classify_error(result.stderr)} [mode: {mode}]"
        )

    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise HTTPException(500, "yt-dlp returned unexpected output — try again.")

    direct_url = info.get("url")
    video_format, audio_format = _parse_requested_formats(info)
    if not direct_url and not video_format:
        raise HTTPException(500, "yt-dlp did not return a direct URL. The video format may be unsupported.")

    selected_height = info.get("height") or (video_format or {}).get("height")
    selected_ext = info.get("ext") or (video_format or {}).get("ext") or "mp4"
    selected_note = info.get("format_note") or (video_format or {}).get("format_note") or ""

    return {
        "title": info.get("title", "video"),
        "mode": "muxed" if video_format and audio_format else "direct",
        "direct_url": direct_url,
        "http_headers": _normalize_headers(info.get("http_headers", {})),
        "video_url": (video_format or {}).get("url"),
        "video_headers": _normalize_headers((video_format or {}).get("http_headers", {})),
        "audio_url": (audio_format or {}).get("url"),
        "audio_headers": _normalize_headers((audio_format or {}).get("http_headers", {})),
        "height": selected_height,
        "format_note": selected_note,
        "ext": selected_ext,
        "format_id": info.get("format_id", ""),
    }, result.stderr


def get_yt_info(url: str, quality: str = "best") -> dict:
    has_cookies = os.path.isfile(COOKIES_PATH)
    attempts: list[tuple[bool, Optional[str]]] = []
    if has_cookies:
        attempts.extend([
            (True, None),
            (True, "tv_downgraded,web_safari,web_creator,web"),
            (True, "ios,web_safari"),
        ])
    attempts.extend([
        (False, "android_vr,web_safari,web_embedded"),
        (False, "tv,ios,web_safari,web"),
        (False, None),
    ])

    errors: list[str] = []
    for use_cookies, player_client in attempts:
        try:
            info, _ = _extract_yt_info(url, quality, use_cookies=use_cookies, player_client=player_client)
            info["auth_mode"] = "cookies" if use_cookies else "anonymous"
            info["player_client"] = player_client or "yt-dlp-default"
            return info
        except HTTPException as exc:
            errors.append(str(exc.detail))

    raise HTTPException(403, "All YouTube extraction attempts failed. " + " | ".join(errors[-2:]))


def get_yt_info_cached(short_id: str, youtube_url: str, quality: str) -> dict:
    """Return cached URL info, refreshing if stale."""
    now = time.time()
    cached = _url_cache.get(short_id)
    if cached and (now - cached["fetched_at"]) < URL_CACHE_TTL:
        return cached

    info = get_yt_info(youtube_url, quality)
    _url_cache[short_id] = {**info, "fetched_at": now}
    return _url_cache[short_id]


def _ffmpeg_headers(headers: dict[str, str]) -> str:
    return "".join(f"{k}: {v}\r\n" for k, v in headers.items())


def _build_mux_process(info: dict) -> subprocess.Popen:
    if not shutil.which("ffmpeg"):
        raise HTTPException(
            500,
            "Higher quality playback requires ffmpeg on the backend. Redeploy with the updated Dockerfile or install ffmpeg locally."
        )

    video_url = info.get("video_url")
    audio_url = info.get("audio_url")
    if not video_url or not audio_url:
        raise HTTPException(500, "Missing adaptive video/audio URLs for muxed playback.")

    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        "-nostdin",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_at_eof", "1",
        "-reconnect_delay_max", "5",
        "-headers", _ffmpeg_headers(info.get("video_headers", {})),
        "-i", video_url,
        "-headers", _ffmpeg_headers(info.get("audio_headers", {})),
        "-i", audio_url,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c", "copy",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "-f", "mp4",
        "pipe:1",
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


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
        "version": "2.3.0",
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

    base_url = (os.getenv("BASE_URL") or str(request.base_url).rstrip("/")).rstrip("/")

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

    direct_url = info.get("direct_url")
    req_headers: dict[str, str] = info.get("http_headers", {}).copy()

    range_header = request.headers.get("range")
    if range_header:
        req_headers["Range"] = range_header

    client = httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30.0, read=None))

    try:
        if info.get("mode") == "muxed" and info.get("video_url") and info.get("audio_url"):
            mux_proc = _build_mux_process(info)

            async def muxed_stream_generator():
                try:
                    while True:
                        chunk = await asyncio.to_thread(mux_proc.stdout.read, 65536)
                        if not chunk:
                            break
                        yield chunk
                finally:
                    if mux_proc.stdout:
                        mux_proc.stdout.close()
                    if mux_proc.poll() is None:
                        mux_proc.kill()
                        mux_proc.wait(timeout=5)
                    await client.aclose()

            ext = info.get("ext") or "mp4"
            resp_headers: dict[str, str] = {
                "Content-Type": "video/mp4" if ext == "mp4" else "video/webm",
                "Content-Disposition": _content_disposition(entry["title"], ext),
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Expose-Headers": "Content-Disposition, X-Selected-Quality",
                "X-Selected-Quality": str(info.get("height") or entry.get("quality") or "best"),
            }
            return StreamingResponse(muxed_stream_generator(), status_code=200, headers=resp_headers)

        req_obj = client.build_request("GET", direct_url, headers=req_headers)
        source_resp = await client.send(req_obj, stream=True)

        if source_resp.status_code == 403:
            await client.aclose()
            _url_cache.pop(short_id, None)
            info = await asyncio.to_thread(
                get_yt_info_cached,
                short_id,
                entry["youtube_url"],
                entry.get("quality", "best"),
            )
            direct_url = info["direct_url"]
            req_headers = info.get("http_headers", {}).copy()
            if range_header:
                req_headers["Range"] = range_header
            client = httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30.0, read=None))
            req_obj = client.build_request("GET", direct_url, headers=req_headers)
            source_resp = await client.send(req_obj, stream=True)
            if source_resp.status_code == 403:
                await client.aclose()
                _url_cache.pop(short_id, None)
                raise HTTPException(
                    502,
                    "YouTube CDN rejected the stream after refresh. Regenerate the link; if it repeats, use another backend IP."
                )

        async def stream_generator():
            try:
                async for chunk in source_resp.aiter_bytes(65536):
                    yield chunk
            finally:
                await source_resp.aclose()
                await client.aclose()

        ext = info.get("ext") or "mp4"
        resp_headers: dict[str, str] = {
            "Content-Type": "video/mp4" if ext == "mp4" else "video/webm",
            "Accept-Ranges": "bytes",
            "Content-Disposition": _content_disposition(entry["title"], ext),
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges, Content-Disposition, X-Selected-Quality",
            "X-Selected-Quality": str(info.get("height") or entry.get("quality") or "best"),
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
