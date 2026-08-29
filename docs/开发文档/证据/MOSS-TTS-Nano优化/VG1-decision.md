# VG1-GATE：当前主机 VoiceGenerator 可用性裁决

状态：**2026-08-29 `NO-GO`。当前 Apple M4 / 16 GiB 不加载、不下载、不产品化 VoiceGenerator；capability 继续隐藏。**

## 1. 汇合证据

- 官方核验：[VG0-official.md](./VG0-official.md)
- 本机拓扑：[VG0-local-topology.md](./VG0-local-topology.md)
- 可复核 dry-run：[VG1/metrics.json](./VG1/metrics.json)

官方固定 VoiceGenerator revision 为 `97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4`，full codec revision 为 `3cd226ba2947efa357ef453bcad111b6eafba782`。VoiceGenerator 与 codec 的完整快照约 `10.566 GiB`；官方 CPU/FP32 路径的静态权重下界约 `14.487 GiB`，尚未计算激活、KV cache、allocator、OS、QwenPaw 和 Nano。官方示例只有 CUDA→CPU 路径，没有可据此宣称支持的 MPS 路径。

当前宿主只有 16 GiB，Docker VM 约 7.75 GiB，且核验时 swap 已使用约 4.68 GiB，无法满足计划要求的至少 4 GiB 宿主安全余量。metadata-only dry-run 明确记录 0 次模型下载、0 次模型导入/加载、0 次真实生成、0 次 Nano 二次克隆，决策为 `hide`。

## 2. 裁决

- `VG1-GATE=NO-GO`：W4 的 VoiceGenerator contract/migration/runtime/domain/AI bridge/UI 产品化工作包不启动。
- 当前页面不得出现可点击的“根据人物生成专属新音色”，也不得用官方 preset 分配伪装生成成功。
- 允许的降级只有“自动分配官方音色”：按人物稳定 ID 与作品语言，在固定 18 个官方 preset 的对应语言组中稳定选择，并调用既有原子直用 API。它不推断性别、年龄或姓名，也不生成新声音。
- 真正的人物卡 AI 分析→VoiceGenerator 新音色能力保留为未来能力；只有迁移到至少 24 GiB、建议 32 GiB 的隔离主机并通过真实峰值、取消、卸载、Nano 二次克隆和听感门禁后，才重新评估。

## 3. 降级路径验证

前端新增确定性 `stableOfficialVoiceAssignment(characterId, targetLanguage)`，人物单项和未配置人物批量入口都复用 `official-voice-selections` 原子服务、settings/binding CAS 与幂等键。文案固定说明“这不是新音色生成”。聚焦验证：

```text
pnpm typecheck
PASS

pnpm vitest run \
  frontend/src/narration/character-voice-roster.test.ts \
  frontend/src/narration/t2-gate.integration.test.ts
Test Files 2 passed; Tests 13 passed
```
