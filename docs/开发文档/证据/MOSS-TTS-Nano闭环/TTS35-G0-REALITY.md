# TTS35-G0 当前事实冻结

状态：**PARTIAL / SOURCE-GATE-BLOCKED**

取证时间：2026-08-29（Asia/Shanghai）

本证据只执行只读检查。由于计划 36 的 `20260829_0033`、人物工作区和模型证据链仍处于另一任务的未提交施工状态，计划 35 的源码、迁移、公共契约和入口接线尚未开始。

## Git 与迁移前置门禁

- 当前分支：`main`
- 当前提交：`9e5826b5f6fe4ed429290ad7c90645ccc20b4bab`（`origin/main` 同步）
- 计划 36 的 `backend/migrations/versions/20260829_0033_model_execution_evidence_v2.py` 仍为未跟踪文件；其共享后端与前端文件仍有未提交修改。
- 长期 PostgreSQL `alembic_version`：`20260829_0031`
- 裁决：计划 35 的 `0034` 与源码施工不得开始；先等待计划 36 形成稳定提交。

## 长期运行事实

`GET /api/ai-novel-world-2026/health` 返回：

- PawApp `version=0.4.0`、总体 `status=ready`；
- PostgreSQL 18.6 可连接；
- Nano `technical_enabled=true`、`lifecycle_status=ready`；
- Sidecar 可达、模型 ready、当前按需卸载状态 `model_loaded=false`；
- Sidecar 协议 `moss-tts-sidecar/1.1`；
- 模型 fingerprint `3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d`；
- production runtime `product_requested=true`、`lifecycle_status=ready`、播放器、digest keyring、生产后端和 worker 均 ready；
- `reference_clone_ready=false`，本计划不改变第三方参考录音边界。

Compose 三个长期容器均为 healthy：

- QwenPaw image ID：`sha256:ea2c0858b94a6522821cceb73593bbea5f02c85fee2f08a8d7386ea90d9f15b1`
- Nano Sidecar image ID：`sha256:3d767dfea08044e1c41a0a37ce1bb8ac988a20930fb37095622cabc75bc8e216`
- PostgreSQL 固定镜像：`pgvector/pgvector:0.8.6-pg18@sha256:2ba9ca5f2e7daa0f0e7723cba1ee9167bab54efd3640516a44ac1a928dd67e7a`

## 已安装 PawApp 与官方音色

- 已安装 `plugin.json` SHA-256：`e1b3fd6ec4c7fb5170587e9a1f050bc95feb7070d1716092b24baf34a654b0cc`
- 已安装 `frontend/dist/index.js` SHA-256：`49b56e7c739996b7872ab3b620d32d8106cee63484ca60aab2ebc6693e7b3f17`
- 排除 `__pycache__` 后的已安装插件有序文件清单聚合 SHA-256：`23aac1f23d37ab8148ae4e0ad336011c6e18fcebe26c04a43ce6e163607f71b3`
- `GET /api/ai-novel-world-2026/voice-presets` 返回 `moss-tts-official-preset-catalog/2.0`。
- 共 18 项，18 项均 `selectable_now=true`，18 项均 `previewable_now=true`。
- 本轮未执行试听、绑定或合成，因此以上只证明目录和只读能力投影，不替代真实音频与写入验收。

## 只读命令

```text
git status --short
git log -5 --oneline --decorate
curl -fsS http://127.0.0.1:18088/api/ai-novel-world-2026/health
curl -fsS http://127.0.0.1:18088/api/ai-novel-world-2026/voice-presets
docker compose ps --format json
docker compose exec -T postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select version_num from alembic_version order by version_num"'
docker inspect --format '{{.Image}}' ai-novel-2026-qwenpaw-lab
docker inspect --format '{{.Image}}' ai-novel-2026-moss-tts-sidecar
```

## 退出条件

只有同时满足以下条件，`TTS35-G0` 才能从 `PARTIAL` 转为 `PASS`：

1. 计划 36 形成稳定 Git 提交且 `0033` 不再未提交；
2. 从该提交创建独立 `codex/tts35-*` worktree；
3. 在独立 worktree 重新确认 Alembic 单头为 `0033`，并冻结计划 35 公共契约后再开始源码施工。
