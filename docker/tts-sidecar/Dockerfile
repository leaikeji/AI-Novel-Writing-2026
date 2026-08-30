# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
ARG PYTHON_BASE=python:3.11.16-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b

FROM ${PYTHON_BASE} AS ffmpeg-builder
ARG DEBIAN_SNAPSHOT=20260825T000000Z
ARG FFMPEG_SHA256=cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635
RUN printf '' > /etc/apt/sources.list.d/debian.sources \
    && printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/%s bookworm main\n' "$DEBIAN_SNAPSHOT" > /etc/apt/sources.list \
    && printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/%s bookworm-security main\n' "$DEBIAN_SNAPSHOT" >> /etc/apt/sources.list \
    && apt-get -o Acquire::Check-Valid-Until=false update \
    && apt-get install --yes --no-install-recommends build-essential ca-certificates curl xz-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN --mount=type=cache,id=ai-novel-2026-tts-ffmpeg-source,target=/var/cache/ai-novel-world-tts,sharing=locked \
    archive=/var/cache/ai-novel-world-tts/ffmpeg-9.0.1.tar.xz \
    && partial="$archive.part" \
    && if ! echo "${FFMPEG_SHA256}  $archive" | sha256sum --check --strict >/dev/null 2>&1; then \
         rm -f "$archive"; \
         curl --fail --location --proto '=https' --tlsv1.2 \
           --retry 10 --retry-all-errors --retry-delay 2 \
           --connect-timeout 30 --speed-time 300 --speed-limit 1024 --max-time 3600 \
           --continue-at - --output "$partial" \
           https://ffmpeg.org/releases/ffmpeg-9.0.1.tar.xz; \
         echo "${FFMPEG_SHA256}  $partial" | sha256sum --check --strict; \
         mv "$partial" "$archive"; \
       fi \
    && echo "${FFMPEG_SHA256}  $archive" | sha256sum --check --strict \
    && tar --extract --file "$archive" \
    && cd ffmpeg-9.0.1 \
    && ./configure \
      --prefix=/opt/ffmpeg \
      --cc=/usr/bin/gcc \
      --disable-doc --disable-debug --disable-network --disable-autodetect \
      --disable-sdl2 --disable-ffplay --disable-shared --enable-static \
      --disable-gpl --disable-version3 --disable-nonfree --disable-everything \
      --enable-ffmpeg --enable-ffprobe --enable-protocol=file --enable-protocol=pipe \
      --enable-demuxer=wav --enable-demuxer=flac --enable-demuxer=mov \
      --enable-decoder=pcm_s16le --enable-decoder=pcm_s24le --enable-decoder=pcm_f32le \
      --enable-decoder=flac --enable-decoder=aac --enable-encoder=aac \
      --enable-encoder=flac --enable-encoder=pcm_s16le --enable-muxer=ipod \
      --enable-muxer=mp4 --enable-muxer=flac --enable-muxer=wav \
      --enable-filter=aresample --enable-filter=aformat \
    && make -j2 \
    && make install \
    && install -D -m 0444 COPYING.LGPLv2.1 /opt/ffmpeg/licenses/COPYING.LGPLv2.1 \
    && install -D -m 0444 LICENSE.md /opt/ffmpeg/licenses/LICENSE.md

FROM ${PYTHON_BASE} AS dependency-runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=0 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/opt/ffmpeg/bin:$PATH \
    MOSS_FFMPEG_BUILD_ID=ffmpeg-9.0.1-lgpl-narrow-linux-arm64-v1 \
    MOSS_TTS_SIDECAR_TOKEN_FILE=/run/secrets/moss_tts_sidecar_token \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_DATASETS_OFFLINE=1 \
    TOKENIZERS_PARALLELISM=false

WORKDIR /opt/ai-novel-world/tts-sidecar
COPY docker/tts-sidecar/requirements.lock ./requirements.lock
RUN --mount=type=cache,id=ai-novel-2026-tts-pip-aarch64,target=/root/.cache/pip,sharing=locked \
    test "$(uname -m)" = "aarch64" \
    && echo "196885c7bdb417ca6df16406ca8eb9784a29a993726c5e75ded3df832d6f0ac3  requirements.lock" | sha256sum --check --strict \
    && python -m pip install --require-hashes --only-binary=:all: \
      --timeout 600 --retries 5 \
      --report /opt/ai-novel-world/tts-sidecar/pip-install-report.json \
      -r requirements.lock \
    && python -m pip check

COPY --from=ffmpeg-builder /opt/ffmpeg /opt/ffmpeg
COPY --from=ffmpeg-builder /usr/lib/aarch64-linux-gnu/libgomp.so.1* /usr/lib/aarch64-linux-gnu/
COPY docker/tts-sidecar/model-source.lock.json \
     docker/tts-sidecar/NOTICE \
     docker/tts-sidecar/THIRD_PARTY_NOTICES.md \
     docker/tts-sidecar/entrypoint.py \
     docker/tts-sidecar/verify_runtime.py ./
RUN echo "c6491f44c87e05d3d8075a102d65c019e7b40608a977baa05366929e7684e137  model-source.lock.json" | sha256sum --check --strict \
    && python verify_runtime.py \
    && install -d -o 65532 -g 65532 -m 0750 /opt/moss-assets

LABEL org.opencontainers.image.title="AI小说世界2026 MOSS-TTS dependency Sidecar" \
      org.opencontainers.image.description="T1-DEP Linux/arm64 dependency layer; fail-closed until T1-B" \
      org.opencontainers.image.version="t1-dep" \
      ai.novel.world.project="AI小说世界2026" \
      ai.novel.world.work-package="T1-DEP" \
      ai.novel.world.business-runtime="absent"

USER 65532:65532
ENTRYPOINT ["python", "/opt/ai-novel-world/tts-sidecar/entrypoint.py"]

FROM dependency-runtime AS production-runtime
COPY --chown=65532:65532 \
     backend/narration/sidecar_server.py \
     backend/narration/runtime.py \
     backend/narration/model_assets.py \
     /opt/ai-novel-world/tts-sidecar/runtime/
COPY --chown=65532:65532 \
     scripts/tts/install_models.py \
     docker/tts-sidecar/init_runtime_volumes.py \
     /opt/ai-novel-world/tts-sidecar/runtime/
RUN echo "6051c4e689980c732aa7d7a1a95e46f2273075a91509232942a775dd6de79242  runtime/sidecar_server.py" | sha256sum --check --strict \
    && echo "4c74dcc8cbd05615e5dbca1bb629777d052cce4b2d85aee773e93219b83e9593  runtime/runtime.py" | sha256sum --check --strict \
    && echo "868a8c9d73fedaea04ffd4293e518962154efabcdbd6e623bbf351a842e853e0  runtime/model_assets.py" | sha256sum --check --strict \
    && echo "4513337e3819ef5b4c5d08c83baa3710587f62d97c1135e74e712ebdfef58385  runtime/install_models.py" | sha256sum --check --strict \
    && echo "caf31a1cea8021970ab70fc489ee7a1c6fff9535bbfa269805c463e61e023e15  runtime/init_runtime_volumes.py" | sha256sum --check --strict

LABEL org.opencontainers.image.title="AI小说世界2026 MOSS-TTS production Sidecar" \
      org.opencontainers.image.description="T1-B Linux/arm64 private MOSS-TTS-Nano runtime" \
      org.opencontainers.image.version="t1-b" \
      ai.novel.world.project="AI小说世界2026" \
      ai.novel.world.work-package="T1-B" \
      ai.novel.world.business-runtime="present" \
      ai.novel.world.protocol="moss-tts-sidecar/1.1" \
      ai.novel.world.model-fingerprint-sha256="3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d"
ENTRYPOINT ["python", "/opt/ai-novel-world/tts-sidecar/runtime/sidecar_server.py"]
