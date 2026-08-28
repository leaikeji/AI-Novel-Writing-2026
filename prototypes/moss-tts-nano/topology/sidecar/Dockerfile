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
RUN curl --fail --location --proto '=https' --tlsv1.2 \
      --output ffmpeg-9.0.1.tar.xz https://ffmpeg.org/releases/ffmpeg-9.0.1.tar.xz \
    && echo "${FFMPEG_SHA256}  ffmpeg-9.0.1.tar.xz" | sha256sum --check --strict \
    && tar --extract --file ffmpeg-9.0.1.tar.xz \
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

FROM ${PYTHON_BASE} AS protocol
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=0
WORKDIR /app
COPY topology/sidecar/sidecar_protocol.py topology/sidecar/sidecar_server.py topology/sidecar/sidecar_client.py topology/sidecar/pawapp_harness.py /app/
COPY model-sources.lock.json /app/model-sources.lock.json
USER 65532:65532
ENTRYPOINT ["python", "/app/sidecar_server.py"]

FROM protocol AS runtime
USER 0:0
COPY python-requirements.lock /app/python-requirements.lock
RUN test "$(uname -m)" = "aarch64" \
    && python -m pip install --no-cache-dir --require-hashes --only-binary=:all: \
      --report /app/pip-install-report.json -r /app/python-requirements.lock \
    && python -m pip check
COPY --from=ffmpeg-builder /opt/ffmpeg /opt/ffmpeg
# Torch/Torchaudio's fixed Linux arm64 wheels dynamically require GNU OpenMP.
# Copy the runtime from the same pinned Debian snapshot builder instead of
# adding a mutable runtime apt transaction.
COPY --from=ffmpeg-builder /usr/lib/aarch64-linux-gnu/libgomp.so.1* /usr/lib/aarch64-linux-gnu/
ENV PATH=/opt/ffmpeg/bin:$PATH \
    MOSS_FFMPEG_BUILD_ID=ffmpeg-9.0.1-lgpl-narrow-linux-arm64-v1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_DATASETS_OFFLINE=1 \
    TOKENIZERS_PARALLELISM=false
USER 65532:65532
