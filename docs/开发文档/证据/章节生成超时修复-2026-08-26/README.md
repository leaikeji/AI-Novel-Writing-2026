# 章节生成超时修复与真实作品恢复（2026-08-26）

状态：**章节生成故障已修复并在真实 QwenPaw 运行态验证；目标作品第 1 章已生成并形成不可变 revision。**

## 1. 故障事实

- 作品：`刑侦1988:档案里消失的人`
- 章节：`护城河的绳结`
- 原任务 `c508b1b6-43d8-4f54-af0f-6f5d295ef6d0` 长时间停留在 `running`，期间保持一个 `idle in transaction` 数据库连接。
- 原任务最终由 `bailian / qwen3.7-plus` 返回空正文，终态为 `failed`，正式正文保持 0 字。
- 修复后对同一模型的第 2 次真实调用在 300 秒硬上限结束；模型用量记录增加，但仍未形成可用最终正文。该结果证明当前 `qwen3.7-plus` 尚不能承担本项目章节正文生产，不应继续机械重试。

## 2. 修复范围

- 新增请求级 300 秒硬上限；即使底层 Provider 协程不响应取消，HTTP 请求也能按时结束。
- 模型等待前释放 SQLAlchemy payload-read 事务，禁止外部模型调用占用长事务。
- 显式处理请求取消，失败时保证正式正文不变。
- 在读取历史或再次生成前回收超过“硬上限 + 30 秒宽限”的陈旧 `running` 任务。
- 前端新增“章节正文生成失败”弹窗和持久错误信息，明确说明失败原因及正文保护状态。

## 3. 实际验证

- Python 定向单元测试：`43 passed`。
- PostgreSQL 18 隔离库：超时回收、严格模型证据和并发 attempt 三项 `3 passed`；临时测试库测试后删除。
- 前端：TypeScript typecheck 通过，Vitest `55 files / 448 tests passed`，Vite build 通过。
- PawApp 通过 QwenPaw 公开 `plugin install --force` 热加载；健康接口为 `ready`。
- 全量 Python：`768 passed, 17 failed, 88 skipped`；17 个失败全部来自同期未完成的朗读 `script_contracts` 源码/fixture 漂移，不属于本修复，未被本任务修改或错误记为通过。

## 4. 真实章节结果

- 将 `AI小说作家` Agent 有效模型切换为此前已通过章节 E2E 的 `minimax-cn / MiniMax-M3`。
- 真实生成耗时约 9 秒，请求模型与实际模型一致。
- 候选 `b30b4927-1a5d-46bf-a242-3e29ef7981a1`：1129 个可见字符，`validation_state=meets_target`。
- 经 CAS 采用后生成 revision `66f0a0f5-d8f4-4619-9aa1-2dd717dd10da`，来源 `ai_candidate_adopt`；章节 `draft_version=2`，正文哈希为 `bf55900b6c1075b645188c49d935f42562af2a0d9978f8b5aed59f85278ac597`。
- 页面已真实刷新核验：章节目录和编辑器均显示 1129 字；`AI小说作家` 当前有效模型保持 `MiniMax-M3`。

## 5. 结论

章节生成链路已经恢复。模型仍严格跟随 `AI小说作家` Agent，不新增第二套选择器或静默回退；但“可选择”不等于“所有模型未经验收即可生产”。`qwen3.7-plus` 必须完成独立兼容修复与真实章节验收后，才能重新作为正文生产模型。
