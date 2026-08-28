# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
ARG QWENPAW_BASE_IMAGE=agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/qwenpaw:v2.1.0@sha256:847fa1b01969492587fcf9b01f28fef97cb4039de92148c08c49486b94b3d912
ARG PYTHON_BASE=python:3.11.16-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b

FROM ${PYTHON_BASE} AS narration-ffmpeg-builder
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
    test "$(uname -m)" = "aarch64" \
    && archive=/var/cache/ai-novel-world-tts/ffmpeg-9.0.1.tar.xz \
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

FROM ${QWENPAW_BASE_IMAGE}

COPY requirements.txt /tmp/ai-novel-world-2026-requirements.txt
RUN /app/venv/bin/python -m pip install --no-cache-dir --timeout 600 --retries 5 \
    -r /tmp/ai-novel-world-2026-requirements.txt \
    && rm /tmp/ai-novel-world-2026-requirements.txt \
    && install -d -m 0555 /opt/ai-novel-world/narration-model-metadata

# Reuse the exact fixed LGPL-narrow toolchain from the existing TTS Sidecar
# build graph.  This adds no model runtime and does not overwrite QwenPaw core;
# the PawApp only needs ffmpeg/ffprobe to validate and publish returned audio.
COPY --from=narration-ffmpeg-builder /opt/ffmpeg /opt/ffmpeg

ENV PATH=/opt/ffmpeg/bin:$PATH \
    MOSS_FFMPEG_BUILD_ID=ffmpeg-9.0.1-lgpl-narrow-linux-arm64-v1
