# CPC-INT 施工验收记录

日期：2026-08-26（Asia/Shanghai）

## 专项通过

- `tests/test_character_profile_services.py` + `tests/test_model_runtime.py`：66 passed。
- `tests/test_character_profile_completion_api.py`：19 passed。
- `tests/test_character_profile_completion_integration.py`：专用 `ai_novel_world_2026_test` PostgreSQL 中 6 passed，测试后专项小说残留为 0。
- `frontend/src/character-profile-completion.test.ts`：10 passed。
- `pnpm typecheck`：在朗读测试文件合并进入工作区前通过；生产 bundle `pnpm build` 通过。
- `scripts/package_plugin.py` 通过；Skill/安装/QwenPaw 契约 43 passed。
- 隔离迁移验证：`0016 -> 0015 -> 0016`、重复 upgrade 通过，最终只有 `20260826_0016` 一个 head。
- 生产库：事前限权备份成功，从 `0015` 升级为 `0016`；PawApp 热安装成功。
- 真实浏览器：桌面与 390x844 窄屏的分析入口可见可用，无水平溢出；确认弹窗显示 `deepseek / deepseek-v4-flash`、“只生成候选，不会自动写入”。

## 生产数据不变式

弹窗验收后选择取消，未触发模型。读取校验结果：

- active roles = 6
- roles with personality = 0
- character profile jobs = 0
- character profile apply batches = 0

## 共享门禁阻塞

- 全量 Python 仍有 6 个朗读 script API 响应契约失败。
- 全量 Vitest 中 3 个朗读测试文件因 `script-contracts.ts` 语法错误无法 transform；后续并入的朗读测试还有参数数量不匹配。
- 总安装验证预期 narration runtime 为 `disabled`，当前其他专项实际运行态为 `ready` 且 `product_visible=false`，因此总验证未绿。

本专项未修改上述朗读文件，也未将其失败记为通过。
