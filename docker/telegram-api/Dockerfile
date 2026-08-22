FROM debian:bookworm-slim AS builder

ARG TELEGRAM_BOT_API_COMMIT=adfd7f6a8e990272851777eeb3ae0def4216f161
ARG BUILD_JOBS=2

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        cmake \
        g++ \
        git \
        gperf \
        libssl-dev \
        make \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /source
RUN git init \
    && git remote add origin https://github.com/tdlib/telegram-bot-api.git \
    && git fetch --depth 1 origin "${TELEGRAM_BOT_API_COMMIT}" \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "${TELEGRAM_BOT_API_COMMIT}" \
    && git submodule update --init --recursive --depth 1

RUN cmake -S /source -B /build \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/telegram \
    && cmake --build /build --target install --parallel "${BUILD_JOBS}"


FROM debian:bookworm-slim AS runtime

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates libssl3 libstdc++6 zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 telegram \
    && useradd --uid 10001 --gid telegram --no-create-home --shell /usr/sbin/nologin telegram \
    && install --directory --owner telegram --group telegram /var/lib/telegram-bot-api \
    && install --directory --owner telegram --group telegram /tmp/telegram-bot-api

COPY --from=builder /opt/telegram/bin/telegram-bot-api /usr/local/bin/telegram-bot-api
COPY entrypoint.sh /usr/local/bin/telegram-api-entrypoint
RUN chmod 0555 /usr/local/bin/telegram-bot-api /usr/local/bin/telegram-api-entrypoint

USER telegram:telegram
WORKDIR /var/lib/telegram-bot-api
EXPOSE 8081

ENTRYPOINT ["/usr/local/bin/telegram-api-entrypoint"]
