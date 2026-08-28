# T4-PRESET：个人本地官方预设集成记录

状态：**HISTORICAL_18_PRESET_INTEGRATION_RECORD / PRODUCT_SCOPE_SUPERSEDED_TO_ZH6 / REAL_NANO_BASELINE_READY / REAL_PRODUCT_VALIDATION_HOLD**

日期：2026-08-27（Asia/Shanghai）

> 现行覆盖（2026-08-27）：本文保留 18 项固定 manifest/catalog 与早期集成事实作为技术溯源，不删除历史。最新产品范围只向 UI 和可操作入口提供 6 个中文预设：`onnx.Junhao`、`onnx.Zhiming`、`onnx.Weiguo`、`onnx.Xiaoyu`、`onnx.Yuewen`、`onnx.Lingyu`；其余 12 项不进入当前展示、试听、绑定、合成或 T4 门禁。作者已确认并锁定旁白 `onnx.Zhiming`、林晚 `onnx.Xiaoyu`、沈川 `onnx.Junhao`。独立 controller authority 亦已被现行个人本地信任模型撤销为前置，相关实验仅作非阻断历史记录。

## 本次放行边界

- `HISTORICAL_SUPERSEDED_18_PRESET_PRODUCT_PROJECTION`：本阶段当时曾把固定 manifest 的 18 个 exact preset ID 全部投影为个人本地目录；现行 UI/API 可操作目录已精确收敛为六个中文 preset ID。底层仍不按公众人物或明星标签删减技术目录。
- 新建版本使用 `source_type=preset` 兼容现有领域模型，但 rights 及强类型 provenance 明确为 `source_kind=official_preset`。
- 商业发布／再分发固定投影为 `not_evaluated`，只作信息，不阻断本机展示、试听、锁定、绑定、合成或播放。
- 仓库和插件包仅保存 metadata/hash；不包含 prompt codes、参考音频、生成音频或模型权重。

## 已完成实现

- 后端 metadata-only catalog、`GET /voice-presets`、exact `preset_id` 建版、无 reference 试听、质量确认／锁定、人物绑定与 worker provenance fail-closed。
- Sidecar 启动时核验 manifest raw SHA-256、精确 schema、18 项唯一 voice 与 `T×16` prompt-code shape；推理只接受 exact `onnx.<voice>`。
- `HISTORICAL_SUPERSEDED_18_PRESET_PRODUCT_PROJECTION`：前端曾展示全部 18 项；现行前端与 wire parser 只展示并接受六个中文产品项，18 项 evidence 仅作底层技术校验。旧 `preset_catalog` 仅解析兼容，不再作为新建选项。
- T4-K fixture/readiness/runtime audit/operator envelope 已改为旁白、林晚、沈川三个互异 official preset 证明模式，不再要求三份上传录音或六份 reference/source 媒体。
- 新增线性 Alembic `20260827_0022`，只放宽 official preset preview 的 nullable reference，延迟触发器分开验证 uploaded/reference 和 official-preset/no-reference 闭包。

## 实际验证

- `.venv/bin/python -m pytest -q tests/narration`：全部通过，仅环境依赖型项跳过。
- Sidecar 与镜像契约定向测试：全部通过。
- `pnpm typecheck`：通过。
- `pnpm vitest run frontend/src/narration`：41 个测试文件、406 项通过。
- `pnpm build` 与 `scripts/package_plugin.py`：通过；包内存在 catalog 与 `0022` migration，且无 WAV/MP3/ONNX/safetensors/token/key。
- 现有隔离测试库 `ai_novel_world_2026_tts_test` 在事前备份后由 `0021` 线性升级到 `0022`；实测 head=`20260827_0022`、`voice_previews.reference_asset_id` nullable、scope guard function 唯一。备份位于仓库外临时目录，未进入 Git。

## 仍然 HOLD

- 六个中文产品项均不因商业授权或预设名称而 HOLD；其余 12 项不在当前产品，是语言／产品范围收敛，不是人物标签排除。
- 三个正式预设的真实 Nano 试听、作者确认和 locked/accepted/bound 已完成；完整真实章节最终听检、30 分钟稳定性、精确四桌面组合、CodeMirror/播放器联动和 T4-GATE 仍未完成，因此不将这些后续项表述为已验收。
- controller authority 的旧 HOLD 已被个人本地信任模型取代；Node／Playwright Controller 只是作者／操作员本地固定执行器，不再要求独立签名权威，也不阻断真实运行或 T4-GATE。
