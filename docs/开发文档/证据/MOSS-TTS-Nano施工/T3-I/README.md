# T3-I 独立归因与脚本复核集成 QA

- 工作包：`T3-I` (`PAR-C` 独立 QA)
- 候选结论：**PASS**
- 产品结论：**HOLD**；本证据不代表脚本持久化、Edition 创建、前端入口或真实云端分析已接线，必须继续通过 `T3-GATE`
- 施工时间：2026-08-26 23:31:01–23:38:12 (Asia/Shanghai)
- 初始与结束 HEAD：`9d1ad30e9fbbc70d4b1ccce1e2d9bdb7eaae1ce1`
- 初始工作区：已存在大量与 T3-I 无关的并行施工改动；本工作包未清理、重置、暂存、提交或推送任何文件

## 1. 边界与环境

本工作包只新增两个 Python 集成测试、一个 TypeScript 集成测试和本证据。没有修改后端实现、前端实现、共享契约、入口、迁移、数据库、Docker 或 QwenPaw 上游。所有文本均为项目自造授权短句，不包含用户小说正文。云端路径只使用注入假模型，没有发生真实网络请求。

环境：

- macOS Darwin 25.5.0, arm64
- Python 3.12.13 (`.venv`)
- Node.js 24.19.0
- pnpm 11.19.0
- Vitest 4.1.11
- 未启动、停止、重启或修改任何 Docker 容器；未连接数据库；未读取真实密钥

## 2. 冻结输入

| 输入 | SHA-256 |
| --- | --- |
| T3-A `script_contracts.py` | `c32cd8db3a52ff4a0495ff30947b38a08885c952fd7743b88ee6298a0719656c` |
| T3-B `segmentation.py` | `bb1366e6f557b53658af9d4f5b6e6e905f071ff2ec87d0ee9715478a1873b6e5` |
| T3-C `speaker_rules.py` | `7d72d655be8bf73e8d4d143354c7c3e95a2eee8613ed3a01ebe81ffe5ea25cee` |
| T3-D `cloud_analysis.py` | `2c98d9912bdfba5852dc33af7644c14115976335cd0913e898c3ec2cb21932e1` |
| T3-E `anonymous_speakers.py` | `002c5394053599bf0eceb5bae19ac99d540b7bb9028a339cce84eb9de55907f7` |
| T3-F `casting.py` | `1cae9f321a8f4d9d353d62e6aed2df36924f06b929c09df85002be58d4c730b4` |
| T3-G `confidence.py` | `2d954ff9f455b15e8c845b6aa7bb1fb9e290dd3a761b8e9fd0ee587d4c545699` |
| T3-G `expression.py` | `36acf1b1bb44cabba226dcfdc79ba6ae2be6101716bbbbccfd5cb9d2b0b76156` |
| T3-H `script_review.py` | `f9d259cef19972fe409d4e802cbceef1370bde72b0a99636ac7b309b51b0ecd6` |
| T3-H `script_api.py` | `90e4741f84d0e9175ab51fd676a67603d4e4314565d221cf078dc22600ff3999` |

T3-F 和 T3-G Owner 在最终联合测试前分别确认上述公共接口已稳定；T3-I 只读调用这些接口，没有修改实现。

## 3. 独立测试矩阵

| 门槛 | 独立验证 |
| --- | --- |
| 明确姓名+说话动词准确率 | 10 个自造姓名 × 10 种前置/后置说话标记，共 100 条固定预期；同时要求 high 置信、唯一候选人物和零 issue |
| B/C/G 确定性 | 同一 source/script version 重复分句、归因、情绪/表达分类产生完全相同的 ID 和结果 |
| 人物卡音色稳定 | 同一已配置人物跨两个句段始终解析为同一锁定 `voice_version_id`，音色漂移数为 0 |
| 非法 ID | 非 allowlist 别名记录拒绝建索引；非法显式人物返回 `unknown + B_CHARACTER_REFERENCE_INVALID`；越权场景 ID 直接拒绝 |
| 隐私最小外发 | 仅不确定 target 和前各 1 个相邻句段进入请求；章首/章尾非相邻文本、scope ID、本地 hash、reference audio 和完整人物卡字段不存在于外发 JSON |
| 授权 | 活跃、同作品授权仅调用注入假模型 1 次并绑定 consent 证据；撤销授权时调用数为 0，返回 `F_CONSENT_REVOKED_BEFORE_CALL` |
| `blockers_only` | 零 blocker（warning 可追溯）仅由 service/system 走 `auto_no_blockers`；重复决策与同证据冻结结果相同 |
| `always_review` | 零 blocker 仍留在 `review_required`，自动冻结拒绝，仅 owner 确认后生成 `manual_after_review` |
| blocker 拦截 | `unknown`、低置信和选角未解析在后端决策与前端面板都使批准边界不可用；旧版本无法原地批准 |
| 修正子版本 | 已验证人工复核父版本即使 blocker 已清零也只能继续人工路径；父版本分类必须穷尽且互斥 |
| 重复分析/幂等证据 | 纯函数重复结果完全相同；前端重放使用字节一致的 CAS 请求体与同一 idempotency key；持久层重放仍属 `T3-GATE` 责任 |
| 正文分歧 | `working_copy_diverged` 同时暴露“继续旧快照/用最新正文重新分析”，未显式选择时不可批准 |

## 4. 准确率与失败分类

可复核计数：

```text
accuracy_numerator=100
accuracy_denominator=100
accuracy_percent=100.00
failure_count=0
failure_classes={}
```

因此“明确姓名+说话动词”固定授权短样本的实际结果为 **100/100 = 100.00%**，高于冻结门槛 **≥98%**。这个数字只表示本边界明确的规则样本，不外推为省略主语、隐含轮次或全书归因的整体准确率。

负向用例全部按预期 fail-closed：

- 非 allowlist 人物/场景 ID：拒绝或转为带 blocker 的 `unknown`，非法 `character_id` 输出数为 0。
- 撤销云端授权：假模型调用数为 0。
- 未知 taxonomy、伪造 severity 和未来 taxonomy 版本：拒绝，不降级为 warning。
- 任一 blocker：自动冻结数为 0，旧版本人工冻结数为 0。
- 伪造自动 owner actor、非法路径 UUID、缺失父版本 authority：全部拒绝。

首次前端专项运行出现 `5 passed / 1 failed`；失败原因是测试夹具两次返回了同一个已被消费的 `Response` 对象，不是产品缺陷。夹具改为每次创建新 `Response` 后，最终稳定为 `6/6` 通过。

## 5. 命令与原始计数

### T3-I 最小后端

```bash
.venv/bin/python -m pytest -q \
  tests/narration/test_speaker_attribution.py \
  tests/narration/test_script_review_integration.py
```

```text
................                                                         [100%]
test_speaker_attribution.py: 6
test_script_review_integration.py: 10
合计：16 passed
```

### T3-I 最小前端

```bash
pnpm exec vitest run frontend/src/narration/script-review.integration.test.ts
```

```text
Test Files  1 passed (1)
Tests       6 passed (6)
```

### T3-A–T3-I 后端联合窄回归

```bash
.venv/bin/python -m pytest -q \
  tests/narration/test_script_contracts.py \
  tests/narration/test_segmentation.py \
  tests/narration/test_speaker_rules.py \
  tests/narration/test_cloud_analysis.py \
  tests/narration/test_anonymous_speakers.py \
  tests/narration/test_casting.py \
  tests/narration/test_confidence.py \
  tests/narration/test_script_review.py \
  tests/narration/test_script_api.py \
  tests/narration/test_speaker_attribution.py \
  tests/narration/test_script_review_integration.py
```

```text
test_script_contracts.py: 54
test_segmentation.py: 42
test_speaker_rules.py: 43
test_cloud_analysis.py: 20
test_anonymous_speakers.py: 37
test_casting.py: 33
test_confidence.py: 76
test_script_review.py: 17
test_script_api.py: 22
test_speaker_attribution.py: 6
test_script_review_integration.py: 10
合计：360 passed
```

仅有 1 条已存在的 Starlette/httpx2 弃用警告，无测试失败。

### T3-H + T3-I 前端联合窄回归

```bash
pnpm exec vitest run \
  frontend/src/narration/script-api.test.ts \
  frontend/src/narration/script-review-panel.test.ts \
  frontend/src/narration/script-review.integration.test.ts
```

```text
Test Files  3 passed (3)
Tests       34 passed (34)
```

### 类型和空白检查

```bash
pnpm typecheck
git diff --check -- \
  tests/narration/test_speaker_attribution.py \
  tests/narration/test_script_review_integration.py \
  frontend/src/narration/script-review.integration.test.ts
```

结果：通过。`ruff` 在当前 `.venv` 不可用，因此未伪称执行。

## 6. T3-I 交付文件与 hash

| 文件 | SHA-256 |
| --- | --- |
| `tests/narration/test_speaker_attribution.py` | `8cefd116f82f243fa86c3a1e25b32e50b480dec0a374982b056ae5da5d8b0c3b` |
| `tests/narration/test_script_review_integration.py` | `52ebe435304854e79f606c0036d47697981e1bdb15f1d4675f29cbc8bac17226` |
| `frontend/src/narration/script-review.integration.test.ts` | `e56ff9574a02fce0f021a660d6613c19db195ddd326d771496d1144eb773a48b` |

## 7. 未验证项、门禁建议与回退

本工作包明确未验证：

1. `script_versions.py` 的数据库 round-trip、幂等键重放和崩溃恢复；
2. `backend/app.py` 路由与严格 API backend factory 的真实接线；
3. 自动/人工冻结后的正式 Edition 创建数与持久审计；
4. 真实云端 provider 与真实模型身份；
5. QwenPaw 安装/卸载、真实浏览器、1920×1080 和 2560×1440 UI。低于 1920×1080 的布局不属于当前目标。

`T3-GATE` 必须在入口接线后重复运行本矩阵，并额外证明：同 idempotency key 在真实持久层只产生一个脚本版本/冻结审计/Edition；任一 blocker 时三者的正式新建数均为 0；卸载 PawApp 后不残留路由。

回退范围为本工作包的 4 个新增文件，不需要数据恢复：

- `tests/narration/test_speaker_attribution.py`
- `tests/narration/test_script_review_integration.py`
- `frontend/src/narration/script-review.integration.test.ts`
- `docs/开发文档/证据/MOSS-TTS-Nano施工/T3-I/README.md`

本次没有执行回退，也没有触碰任何其他工作区改动。
