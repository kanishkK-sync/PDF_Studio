FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STORAGE_DIR=/app/storage

# Office runtime, fonts, and shared libraries for PDF/image processing.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice fonts-dejavu-core fonts-liberation \
        libgl1 libglib2.0-0 libgomp1 libstdc++6 libjpeg62-turbo libopenjp2-7 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 studio \
    && mkdir -p /app/storage \
    && chown studio:studio /app/storage

COPY --chown=studio:studio app ./app
USER studio
EXPOSE 8000

# A single worker keeps local job storage and the in-memory IP budget coherent.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
