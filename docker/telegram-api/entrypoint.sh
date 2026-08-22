#!/bin/sh
set -eu

: "${TELEGRAM_API_ID:?TELEGRAM_API_ID is required}"
: "${TELEGRAM_API_HASH:?TELEGRAM_API_HASH is required}"

HTTP_PORT="${PORT:-8081}"
VERBOSITY="${TELEGRAM_API_VERBOSITY:-1}"

exec telegram-bot-api \
    --local \
    --http-port="${HTTP_PORT}" \
    --dir=/var/lib/telegram-bot-api \
    --temp-dir=/tmp/telegram-bot-api \
    --verbosity="${VERBOSITY}"
