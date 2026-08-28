# T2-E 通用音色池与分类位证据

> 状态：`PASS_WITH_PRODUCT_HOLD`
> 日期：2026-08-26
> 工作包：`T2-E`
> 结论：24 个通用角色分类位已可被严格投影与展示；因尚无通过授权、质量与生产验收的声音资产包，产品能力继续失败关闭，不得自动选角、试听或合成。

## 0. 基线、Owner 与冻结输入

- 开工基线：`9b5be4a`（开工时 `main == origin/main`）；本任务当前未获授 Git 提交或推送。
- 唯一写 Owner：主代理 `/root`；未向其他工作包扩大文件范围。
- 开始/结束：2026-08-26 16:49–16:57 CST。
- 冻结输入：[T2-A 契约冻结](../T2-A/README.md)。施工结束时复核哈希：`schemas.py 1e189e…`, `settings_api.py 05b1a6…`, `contracts.ts 9a6272…`, `api.ts 2c6756…`，均与 T2-A 冻结值一致。
- 运行环境：macOS Apple Silicon M4，项目 `.venv` Python 3.11 兼容边界，捆绑 Node/pnpm 运行时。
- 数据/外部副作用：没有连接正式 PostgreSQL，没有启动模型或容器，没有写入用户小说/音频/密钥。

## 1. 实现范围

- 内置 `generic-voice-pack-catalog/1` 分类表，精确包含 24 个稳定 `slot_key`。
- 分类表只是产品分类，强制 `asset_pack_id = null`且授权、质量、生产就绪均为 `false`。
- 无持久化记录时返回 `missing` 与 0/24；存在旧记录时返回 `disabled` 与 0/24，不信任旧记录中的 ready 声明。
- `PUT` 音色池与自动选角规则均在作品范围加锁后结构化失败，不产生部分写入。
- 前端显示状态、可核验覆盖、授权/质量/生产验收数和 24 个分类位；仅提供真实的重读状态动作。
- 前端交叉校验汇总 ready 计数与可核验槽位，不一致时显式报警并保持不可用；作品 ID 不一致时在渲染前拒绝旧投影。

实际修改文件：

- `backend/narration/voice_pool.py`
- `backend/narration/resources/voice_pool_v1.json`
- `tests/narration/test_voice_pool.py`
- `frontend/src/narration/voice-pool-panel.ts`
- `frontend/src/narration/voice-pool-panel.test.ts`
- `frontend/src/narration/styles/t2-e.ts`
- `docs/开发文档/证据/MOSS-TTS-Nano施工/T2-E/README.md`

## 2. 明确非目标与门禁

- 本工作包没有引入音频、模型地址、外部下载链接或可再分发声明。
- 没有自动创建 `VoiceProfileVersion`、没有把 24 个分类位冒充为 24 个可用音色。
- 没有开放“导入音色包”“开始试听”“开始自动选角”等无真实执行链路的按钮。
- `generic_voice_pool` 与 `automatic_generic_casting` 产品能力仍由 T2-A 冻结 capability 和后续门禁控制，本工作包不翻转开关。
- 若未来引入资产包，必须新增授权来源、品质基线、完整性校验、生产试听证据与独立门禁，不得直接把本分类表改成 approved。

## 3. 验收结果

### Python

```text
.venv/bin/python -m pytest tests/narration/test_voice_pool.py -q
9 passed
```

覆盖：24 位完整性、未批准资产/权利/质量/生产声明拒绝、空池投影、单一旧记录失败关闭、多池身份歧义拒绝、写入无副作用、作品范围校验、自动选角门禁和 handler 边界。

### Frontend

```text
pnpm exec vitest run frontend/src/narration/voice-pool-panel.test.ts
1 file passed; 6 tests passed

cd frontend && pnpm typecheck
tsc --noEmit: PASS
```

覆盖：0/24 真实显示、capability 单独翻转仍不可解锁、汇总/槽位不一致失败关闭、跨作品/旧投影拒绝、24 位可检查投影、仅刷新动作、loading/error/integrity 可访问状态。

### 静态复查

```text
git diff --check -- <T2-E files>
PASS
```

## 4. 产物哈希

| 文件 | SHA-256 |
|---|---|
| `backend/narration/voice_pool.py` | `ab369af8a109f5ff95c41cdb2658d1878aa8dca92d290d4564df182ad5a25a72` |
| `backend/narration/resources/voice_pool_v1.json` | `be117304b7e636d004772d08ed0b8c1a25e29981d7869f0cf6164502184e8a98` |
| `tests/narration/test_voice_pool.py` | `f6cdb893edb5c4c98d15c34b7a5f69642550a0ee2ff01c3be70b950b9af20153` |
| `frontend/src/narration/voice-pool-panel.ts` | `1fdbec9fcbb660c0650f952036f6852ad51bc177eada37d731f9ba000f587e9d` |
| `frontend/src/narration/voice-pool-panel.test.ts` | `31a41a7fc0cce6d326028a149904da9a309dc92440216ecbf516d73403f97c55` |
| `frontend/src/narration/styles/t2-e.ts` | `ec06ef84fda01ba88f53d5cba6f017940994ac41a8feae3bfc058e68e1c4c724` |

## 5. T2-GATE 集成说明

- 后端由唯一集成者把 `VoicePoolHandlers` 接入 T2-A 冻结 dispatcher；不得在集成时放宽失败关闭逻辑。
- 前端由唯一集成者将 `createVoicePoolPanel` 放入“通用音色”子页，合并 `T2_E_NARRATION_STYLES`。
- 页面必须传入服务端 overview 中的 `generic_voice_pool` capability；面板内部另外核验池状态与 24/24 四重条件。
- 只有在独立资产包门禁通过且服务端返回完整 `ready` 证据后，未来版本才能评估新增配置动作。

## 6. 人工验收与待验证项

- 已人工复核 JSON：精确 24 位，不含 HTTP URL、音频文件名或模型 ID，不声明资产包可用。
- 已人工复核 UI 操作面：成功态只有“刷新状态”，错误态只有“重新加载”；均使用真实 GET 依赖。
- 本工作包未单独持有 `LOCK-BROWSER`，因此尚未在真实 QwenPaw 页面进行桌面/窄屏截图、焦点顺序与 200% 缩放验收；这些是 T2-H/T2-GATE 的必须项，不能由单元测试替代。
- 尚无可批准声音资产包，因此 24/24 ready、试听、自动选角与生产合成均未验证，也不属于 T2-E 通过结论。

## 7. 回退

本工作包没有迁移、不修改正式数据，也不安装任何音频资产。回退时可删除本证据列出的六个实现/测试文件和本证据目录；不需要数据恢复。
