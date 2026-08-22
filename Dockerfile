FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MEDIA_TMP_ROOT=/tmp/wbot-media

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 wbot \
    && useradd --uid 10001 --gid wbot --no-create-home --shell /usr/sbin/nologin wbot \
    && install --directory --owner wbot --group wbot /app /tmp/wbot-media

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

USER wbot:wbot
CMD ["python", "-m", "wbot.app"]
