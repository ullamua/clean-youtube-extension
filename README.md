```
 .d8888b.  888                                 888      d8b          888               
d88P  Y88b 888                                 888      Y8P          888               
888    888 888                                 888                   888               
888        888  .d88b.   8888b.  88888b.       888      888 88888b.  888  888 .d8888b  
888        888 d8P  Y8b     "88b 888 "88b      888      888 888 "88b 888 .88P 88K      
888    888 888 88888888 .d888888 888  888      888      888 888  888 888888K  "Y8888b. 
Y88b  d88P 888 Y8b.     888  888 888  888      888      888 888  888 888 "88b      X88 
 "Y8888P"  888  "Y8888  "Y888888 888  888      88888888 888 888  888 888  888  88888P'
```

A Chrome extension + self-hostable backend to generate clean, shareable MP4 links for any YouTube video.

---

## File Tree

```
├── extension/          ← Chrome Extension (Manifest V3)
│   ├── manifest.json
│   ├── background.js
│   ├── popup.html / popup.css / popup.js
│   ├── options.html / options.js
│   └── icons/
└── backend/            ← FastAPI Backend (self-host anywhere)
    ├── main.py
    ├── requirements.txt
    ├── Dockerfile
    ├── render.yaml      ← One-click Render deploy
    └── railway.json     ← One-click Railway deploy
```

---

## Setup

### Step 1: Deploy the Backend (pick one)

#### Option A: Run Locally
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```
Backend will be at `http://localhost:8000`

#### Option B: Deploy to Render (free)
1. Push the `backend/` folder to a GitHub repo
2. Go to [render.com](https://render.com) → New → Web Service
3. Connect your repo, select the `backend/` directory
4. Render auto-detects the `Dockerfile` — just click Deploy
5. Your URL will be `https://yt-clean-proxy.onrender.com`

#### Option C: Deploy to Railway
1. Push `backend/` to GitHub
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Railway auto-detects `Dockerfile` and `railway.json`
4. Set env var: `BASE_URL=https://your-app.up.railway.app`
5. Done

#### Option D: Any Docker host
```bash
cd backend
docker build -t yt-clean-proxy .
docker run -p 8000:8000 -e BASE_URL=https://yourdomain.com yt-clean-proxy
```

---

### Step 2: Install the Chrome Extension

1. Download and unzip the extension files
2. Open Chrome → go to `chrome://extensions`
3. Enable **Developer mode** (toggle in top-right corner)
4. Click **Load unpacked**
5. Select the `extension/` folder
6. Done

---

### Step 3: Configure the Backend URL

1. Pin the extension to your toolbar
2. Right-click the extension icon → **Options**
3. Paste your backend URL (e.g. `https://yt-clean-proxy.onrender.com`)
4. Click **Save**

If running locally, the default `http://localhost:8000` works out of the box.

---

## YouTube Authentication (IMPORTANT)

YouTube blocks many server IPs with "Sign in to confirm you're not a bot". To fix this, provide a **cookies.txt** file from a logged-in YouTube session.

### How to get cookies.txt

1. Install a browser extension to export cookies:
   - Chrome: [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
2. Go to [youtube.com](https://youtube.com) and make sure you're logged in
3. Click the cookie export extension → export cookies for youtube.com
4. Save the file as `cookies.txt`

### Upload cookies to your backend

**Option A: Via the extension Settings page** (recommended)
Open Settings → drag and drop `cookies.txt` into the upload zone

**Option B: Via API**
```bash
curl -X POST https://your-backend-url/upload-cookies \
  -F "file=@cookies.txt"
```

**Option C: Include in Docker build**
```bash
cp ~/Downloads/cookies.txt backend/cookies.txt
docker build -t yt-clean-proxy backend/
```

### Check if cookies are configured
```bash
curl https://your-backend-url/
# Look for "cookies_configured": true and "cookies_entries": N
```

### Remove cookies
```bash
curl -X DELETE https://your-backend-url/cookies
# Or use the Delete button in the extension Settings page
```

> ⚠️ **Security note**: Your `cookies.txt` contains your YouTube session. Keep your backend URL private if cookies are uploaded. Cookies may expire periodically — re-export when you see "blocked" errors again.

---

## Test the Backend

```bash
# Health check
curl http://localhost:8000/

# Generate a clean link
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "expire_minutes": 30, "quality": "720"}'
```

Expected response:
```json
{
  "clean_url": "http://localhost:8000/v/a1b2c3d4.mp4",
  "expires_in": "30 min",
  "quality": "720p",
  "title": "Rick Astley - Never Gonna Give You Up.mp4"
}
```

`quality` accepts `360`, `480`, `720`, `1080`, or `best` (default).

---

## Changing the Backend URL Later

**From the extension:**
- Click the extension icon → gear icon (top right)
- Or right-click icon → Options
- Update the URL and click Save

**Environment variable (backend):**
Set `BASE_URL` to your public domain so generated links use the correct hostname.

---

## Features

- **Catppuccin Mocha** purple theme
- Sleek glassmorphic popup with live backend status, cookie status, and video thumbnail preview
- **Quality selector** — choose 360p, 480p, 720p, 1080p, or Best (saved between sessions)
- **Expiry selector** — 5 min, 30 min, 1 hr, 24 hrs, or Never (saved between sessions)
- Works on YouTube **videos** and **Shorts** (including `youtu.be` short links)
- One-click copy & open in new tab
- **Cookie upload UI** — drag-and-drop `cookies.txt` in Settings, view entry count, delete with one click
- Rate limiting (15 req/min per IP)
- Proper MP4 streaming with range request support (correct User-Agent & headers)
- **URL caching** — resolved video URLs are cached server-side, making streams instant
- Works with mpv, VLC, Discord embeds, and browsers
- Graceful error handling for private, age-restricted, members-only, and unavailable videos
- **Cookies support** for YouTube bot-detection bypass
- Upload/delete cookies via API or the Settings page

---

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `GET /` | GET | Health check + status |
| `POST /generate` | POST | Generate a clean link |
| `GET /v/{id}.mp4` | GET | Stream the video (supports `Range`) |
| `POST /upload-cookies` | POST | Upload cookies.txt |
| `DELETE /cookies` | DELETE | Remove cookies from server |

---

## ⚠️ Important Notes

- The backend requires `yt-dlp` installed (included in the Docker image)
- YouTube direct URLs expire after a few hours — use short expiration times for best results
- "Never" expiration links may stop working when YouTube rotates the direct URL — just re-generate
- If you see "Sign in to confirm you're not a bot", upload a fresh `cookies.txt` file
- Streams use single-file MP4 format — no ffmpeg merging required
- This tool is for personal use. Respect YouTube's Terms of Service.

---

## Requirements

- **Backend**: Python 3.10+, yt-dlp (ffmpeg **not required** — streams use single-file MP4 format)
- **Extension**: Any Chromium browser (Chrome, Edge, Brave, Arc, Opera)
