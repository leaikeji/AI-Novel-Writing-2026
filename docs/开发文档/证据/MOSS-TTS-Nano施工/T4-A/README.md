# T4-A 生产请求、Edition 与缓存编排

状态：**`IMPLEMENTED_CANDIDATE_WITH_APP_ENTRY_AND_LIVE_PG_HOLDS`（2026-08-27）**。保存/设置屏障、请求分析、同事务 queued+Edition、voice resolution、ready cache/任务候选、恢复查询及“全量 ready cache、零 job”即时收口已经实现并通过隔离测试；应用入口接线和 live PostgreSQL 尚未完成，不得表述为用户已可生成朗读。

## 1. 已实现

- 客户请求只提交 document、intent、正文 draft/hash、设置 version、force_review 与幂等键；scope、模型四类 fingerprint、审批与授权均由服务端注入。
- 单一短事务依次执行 working-copy 保存屏障、TTS revision、settings snapshot、request、本地脚本分析/批准、`analyzed -> queued`、Edition/segments、cache lookup 和持久 job/render 候选。
- T3 的 `analyzed.completed_at` 在进入 queued 时清除，避免进行中的生成请求携带已完成时间。
- queued Request 与 Edition 由 0017 deferred guard 约束为同事务共存；`source_job_id` 一对一约束继续保护 render publication。
- `analyze_only` 与 `force_review` 路径均保持 Edition/job/render/media 为零；严格复核只创建不可变 snapshot，不改写全书设置。
- ready cache 仅在同 owner/workspace/novel、voice、model、postprocess 与 canonical input 验证通过后复用；跨 request 的 in-flight 转移继续 fail closed。
- `narration-render-input/2` 只把真正改变合成波形的文本、发音、音色、模型、语言、风格、seed 与后处理纳入 render fingerprint；句段 ID、来源定位 hash 和时间线停顿继续严格校验但不破坏跨 Edition 缓存。历史 v1 Edition/Render 仍可原样复现，v1/v2 不跨版本混用。
- 新 Edition 全部命中 authoritative ready render 时不会创建空唤醒任务；编排器以 Request/Manifest 双 CAS 直接发布唯一 Manifest，并把 Request `queued -> rendering -> ready`。精确重放返回既有 Manifest，不重复追加。
- HTTP 暴露冻结三路 API，未安装 backend 时稳定 503；严格拒绝客户端 authority injection、非 RFC4122 UUID、非严格 scalar 和 batch。

## 2. 实际验证

```text
.venv/bin/python -m pytest \
  tests/narration/test_edition_service.py \
  tests/narration/test_narration_requests_api.py -q
25 passed

.venv/bin/python -m pytest \
  tests/narration/test_edition_service.py \
  tests/narration/test_narration_requests_api.py \
  tests/narration/test_domain_services.py \
  tests/narration/test_script_analysis.py \
  tests/narration/test_regeneration.py -q
56 passed

.venv/bin/python -m py_compile \
  backend/narration/requests.py \
  backend/narration/edition_service.py \
  backend/narration/render_cache.py \
  backend/narration/narration_api.py \
  backend/narration/renders.py \
  backend/narration/regeneration.py \
  backend/narration/progress.py
PASS
```

仅出现既存 Starlette TestClient 弃用警告。

## 3. 主集成 HOLD

- 主入口尚未从服务器权威配置构造 `NarrationProductionPolicy`、安装/卸载同一 backend factory 并挂载 router；fingerprint 未就绪时必须继续 503。
- 真实 PostgreSQL 中的整条 HTTP→deferred commit→job rows 流程尚未复跑。
- batch、失败句段重试、人工脚本 mutation、跨 request in-flight transfer 继续 HOLD。

## 4. 文件摘要

```text
backend/narration/requests.py                       8cb31a522f5b703c121796227847a6c441462684fd40b8eb0132cab3e24a57fd
backend/narration/edition_service.py                e4c23fe10b7b9005e5520063163b902d3260ff4175d48682e8c9bb43e35d8f11
backend/narration/render_cache.py                   e82b1f05f472852f879f65473b06f91211767300bcf89a7c1d4e01d6fdcbdc62
backend/narration/narration_api.py                  93e1251c1d71acd04a1998c7544c23160e9bc4f727a14b146c5bdaee129dcc4c
backend/narration/renders.py                        6a2e14ef20b27e2b82478d9db3a231f919976deabe0b8f5b1d2a3badb757265d
backend/narration/regeneration.py                   68f7a67e8b25f869055f4a9cba103381f2deb90f76cb4d4e8e28a6069f0a6b50
tests/narration/test_edition_service.py             4c1bce96b5c45e7b7ef37abca349064e259e95c3536f8651f681d206d93041af
tests/narration/test_narration_requests_api.py      2274b1fd9b25a60c1ce40f2e132898f923232f2cac8b95787be4c9a0c2cf8bce
tests/narration/test_domain_services.py             f06e89fa16a2ee284889e6376b6da3d5781afa248a7f1a63ac01032d586eca39
```
