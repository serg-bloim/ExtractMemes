# syntax=docker/dockerfile:1
FROM python:3.14-slim

# Node.js is required on PATH for yt-dlp to download YouTube sources (ADR 006).
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/

# Runtime deps only (no [dev] extras, no test suite in the image). See ADR 012.
RUN pip install --no-cache-dir .

RUN mkdir -p downloads .runtime

ENTRYPOINT ["extract-memes"]
CMD ["--help"]
