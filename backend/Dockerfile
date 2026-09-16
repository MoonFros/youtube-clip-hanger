# FairClip API — FastAPI + PyAV video engine
# Build context: the backend/ directory
FROM python:3.11-slim

# Node.js for the offline TTS fallback (vendored meSpeak in tts/vendor)
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV FAIRCLIP_DATA=/app/data

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./
RUN mkdir -p data

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
