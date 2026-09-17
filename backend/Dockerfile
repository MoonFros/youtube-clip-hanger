# FairClip API — FastAPI + PyAV video engine
# Build context: the backend/ directory
FROM python:3.11-slim

# nodejs  — offline TTS fallback (vendored meSpeak in tts/vendor)
# ffmpeg  — optional accelerator: preview transcodes, audio extraction and scene
#           detection run 5-20x faster through it than through the PyAV python
#           frame loop. The image works without it, just slower.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV FAIRCLIP_DATA=/app/data

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./
RUN mkdir -p data

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "75"]
