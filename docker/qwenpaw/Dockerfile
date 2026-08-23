ARG QWENPAW_BASE_IMAGE=agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/qwenpaw:v2.1.0@sha256:847fa1b01969492587fcf9b01f28fef97cb4039de92148c08c49486b94b3d912
FROM ${QWENPAW_BASE_IMAGE}

COPY requirements.txt /tmp/ai-novel-world-2026-requirements.txt
RUN /app/venv/bin/python -m pip install --no-cache-dir \
    -r /tmp/ai-novel-world-2026-requirements.txt \
    && rm /tmp/ai-novel-world-2026-requirements.txt
