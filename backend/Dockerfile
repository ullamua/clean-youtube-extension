FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Ensure latest yt-dlp
RUN pip install --no-cache-dir -U yt-dlp

COPY main.py .

# Optional: copy cookies.txt if present (won't fail if missing)
COPY cookies.tx[t] ./

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
