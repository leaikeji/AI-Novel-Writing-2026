# 大纲页面化与生成耗时审计

状态：本轮页面化施工与真实浏览器门禁已完成；耗时结论来自 2026-08-28 对现有任务的只读复核，没有为审计额外发起模型调用。耗时遥测、陈旧任务恢复和上下文瘦身仍属于后续独立立项建议。

证据时间：2026-08-28（Asia/Shanghai）。

## 1. 审计对象

- 小说：`刑侦1988:消失的档案`
- novel id：`d5a1eda8-2961-4406-97f7-4c0aae8b76e7`
- outline draft id：`d83d4d1e-552f-4866-ad65-a41d1b0aff9a`
- 有效模型契约：`follow-agent-effective-v4`
- 任务记录来源：本机运行态公开 API `GET /api/ai-novel-world-2026/creative-generations?scope_type=outline&scope_id=...`

## 2. 已核实事实：真实耗时

以下秒数由任务的 `created_at` 与 `completed_at` 相减，输入字符数是持久化 `model_context` 的 JSON 字符数，不等同于供应商 token 计量。

| kind | 状态 | 模型 | 输入字符 | 输出可见字符 | 完整响应耗时 |
| --- | --- | --- | ---: | ---: | ---: |
| `outline_background` | ready | `bigmodel / glm-5.3-flash` | 626 | 172 | 135 秒 |
| `outline_characters` | ready | `bigmodel / glm-5.3-flash` | 798 | 2906 | 428 秒 |
| `outline_plot` | running | requested `bigmodel / glm-5.3-flash`，无 actual | 3711 | 0 | 未结束；容器重建后仍残留 running |
| `outline_plot` | ready | `bigmodel / glm-5.3-flash` | 3711 | 1502 | 581 秒 |
| `outline_highlight` | ready | `bigmodel / glm-5.3-flash` | 5213 | 359 | 71 秒 |

结论：等待主要发生在真实 Agent／模型调用，不是前端遮罩动画造成。背景约 2 分 15 秒、角色约 7 分 8 秒、成功的情节约 9 分 41 秒；当前数据不足以把耗时进一步归因到供应商排队、模型推理、Agent 工具轮次或网络，因为任务没有保存首 token、末 token、Agent 轮次数和供应商请求耗时。

## 3. 已核实事实：当前调用链

1. 前端 `POST /creative-generations` 后同步等待整个 HTTP 请求完成。
2. 后端先持久化 `CreativeGenerationJob(state=running)`，随后在同一 API 请求中 `await ctx.chat(...)`。
3. 大纲任务通过 `creative_generation_skill(job)` 使用 `story-foundation`，执行 Agent 固定为 `ai-novel-writer`；模型继续跟随该 Agent 的有效模型，没有第二套选择器。
4. 除 `selection_edit` 外，大纲任务只执行一次模型验证尝试；当前长耗时不是应用层静默重试造成。
5. `outline_plot` 的模型上下文包含背景和全部角色。样例中 8 个角色均带较长人物小传，而任务要求模型输出 1200–1800 个中文可见字符，因此输入／输出规模明显高于背景步骤。
6. 一个旧 `outline_plot` 任务在宿主容器中断后仍为 `running`，没有 `actual_provider_id`、`actual_model_id` 或完成时间。现有创建接口没有在读取／启动新任务前自动收敛这种陈旧运行态。
7. `reply_model_audit` 能核对 requested／actual 模型，但 `CreativeGenerationJob` 当前没有持久化 token、首 token、Agent 轮次数、供应商 request id 或分段耗时，不能从现有记录证明“模型没有思考”或精确定位哪一段最慢。

## 4. 技术判断

- 前端多层弹窗和整面空白遮罩放大了等待感，但不是 135–581 秒真实耗时的根因。页面化后应保留原内容可见，并明确显示“失败不覆盖”，改善可感知等待和安全感。
- 情节步骤的 581 秒与较大的角色上下文／较长目标输出相关，但仅凭一个样本不能证明线性因果，也不能据此固定或替换模型。
- 旧任务残留 `running` 是恢复语义缺口：它可能让用户误以为任务仍在执行，也让失败原因不可审计。
- 直接绕过 `AI 小说作家` Agent、硬编码某个供应商或静默切换模型，会违反项目模型权威边界，不能作为本轮“提速”方案。

## 5. 项目建议

按风险和收益排序：

1. 先落地本轮页面化：移除两层确认，生成时保留编辑区，成功后经既有 CAS 自动采用，失败保留原稿。
2. 单独立项增加生成耗时遥测：至少记录 API 总耗时、Agent 调用耗时、首 token、完成时间、轮次数、token usage、供应商 request id；没有这些证据前不做模型优劣结论。
3. 单独立项增加陈旧任务恢复：宿主重启或超过受控阈值后，把不可继续的 `running` 收敛为可解释失败／中断状态，并允许作者显式重试；不得删除历史任务。
4. 对情节上下文做结构化瘦身尖峰：保留稳定角色 ID、姓名、类型、动机／矛盾／弧线等必要字段，避免把全部长小传逐字发送；先用固定样例 A/B 验证质量和耗时，再决定是否上线。
5. 若 QwenPaw 公开契约支持同一 Agent 的流式或可恢复后台执行，可在适配层实现持久化轮询／流式状态；若只能修改上游核心才能实现，按项目偏好停止并记录缺口。

本轮不实施第 2–5 项后端改造；用户当前授权是页面化施工和耗时复核，不能把诊断自动扩成任务队列、第二 Runtime 或模型切换工程。

## 6. 已完成门禁

- 前端：`pnpm typecheck` 通过；`pnpm vitest run frontend/src/outline-workflow.test.ts` 3 项通过；`pnpm test` 87 个文件、805 项通过；`pnpm build` 通过。
- 后端：`.venv/bin/python -m pytest tests/test_outline_generation_context.py tests/test_model_runtime.py -q` 通过，共 55 项。
- 打包：`.venv/bin/python scripts/package_plugin.py` 通过；随后经项目现有公开 QwenPaw CLI 热安装路径生效，未修改 QwenPaw 核心代码，也未重启或清理数据卷。
- 浏览器宽屏：1855×1236 请求视口下，正式大纲页面无弹窗，背景步骤可编辑，只有一个“重新生成”入口，文档与工作区无横向溢出，控制台无 error。
- 浏览器窄屏：1280×800 请求视口下，工作台、页面和底部按钮均无横向溢出；实测 `document / workbench / workspace / footer` 的 `clientWidth` 与 `scrollWidth` 分别一致。
- 交互：从章节数点击“跳过 AI，直接填写背景”可直接进入背景编辑步骤；没有发起模型调用。未点击“生成／重新生成”，避免为了 UI 验收产生新的高成本模型任务或覆盖现有草稿。
- 视觉比较：源稿与最终背景步骤的同图证据为 `14-最终设计对照.png`；完整增量结论已追加到项目根 `design-qa.md`。

完整插件安装前置全量 Python 测试曾运行到 2429 项通过、116 项跳过、1 项失败；唯一失败是当前工作区既有朗读改动导致 `tests/narration/test_run_local_chapter_e2e.py::test_real_popen_discards_launcher_output_instead_of_using_pipes` 未传新增的 `status_file`，与本轮大纲前端及生成调用链无关。本轮没有越界修改朗读施工。

## 7. 浏览器证据

- `12-最终窄屏.png`：1280×800 下完整工作区，无横向裁切。
- `13-最终宽屏.png`：背景编辑步骤、白底可编辑区、重新生成和上一步／下一步。
- `14-最终设计对照.png`：批准源稿与最终实现的同一比较输入。
- `15-移除重复步骤提示-宽屏.png`：1813×1236 下仅保留一套五步进度图。
- `16-移除重复步骤提示-窄屏.png`：1280×800 下重复提示为 0，页面无横向溢出。
- `17-重复步骤提示-修复前后对照.png`：修复前后全图及步骤区聚焦对比。
- `18-移除冗余提示-宽屏.png`：1813×1236 请求视口下，背景内容直接显示，不再出现成功提示条和可编辑副文案。
- `19-移除冗余提示-窄屏.png`：1280×800 请求视口下的同状态复查，无横向溢出。
- `20-冗余提示-修复前后对照.png`：背景步骤修复前后全图与聚焦区对比。

## 8. 2026-08-28 重复步骤提示修复

- 已删除五步进度图下方重复的“第 N 步，共 5 步”胶囊提示、废弃常量和对应样式；上方五步图、当前步骤内容和底部动作保持不变。
- 自动化门禁：`pnpm vitest run frontend/src/outline-workflow.test.ts` 3 项通过，`pnpm typecheck` 与 `pnpm build` 通过，`git diff --check` 通过。
- 运行态：插件已通过公开热安装路径生效；宽屏和窄屏 DOM 均实测 `.mb-outline-progress-hint` 数量为 0、`.mb-outline-steps` 数量为 1，控制台无 error / warning。
- 本轮没有发起任何模型生成，也没有修改大纲草稿、正式大纲或小说正文。

## 9. 2026-08-28 背景／情节冗余提示清理

- 已删除生成成功后整行显示的“已生成、可直接修改、失败不清空”提示状态与渲染节点；错误提示、生成中进度及失败保留原内容的异常反馈继续保留。
- 已删除背景和情节标题下方的“生成结果直接显示在这里，也可以手动修改”副文案；标题、正文编辑框、重新生成和底部动作不变。
- 自动化门禁：`pnpm vitest run frontend/src/outline-workflow.test.ts` 3 项通过，`pnpm typecheck` 与 `pnpm build` 通过。
- 运行态：公开热安装完成；第 2 步实测成功提示条为 0、目标副文案为 0、五步图为 1，宽屏／窄屏均无页面横向溢出，控制台无 error / warning。
- 浏览器复查只使用“跳过 AI”进入已有背景步骤，没有发起模型生成；未改写背景正文、正式大纲或小说正文。
