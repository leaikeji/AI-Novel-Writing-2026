# 开发计划 49：TTS 复查收尾与部署前兼容性加固

状态：**V1.1 已完成二次复查与方案修订，等待用户批准施工；本文档只冻结修复、验收和发布门禁，尚未修改 TTS 源码、数据库或长期环境。**

日期：2026-09-01（Asia/Shanghai）

## 一、背景与复查结论

计划 44、45和 47 的当前候选实现已通过大量自动化、隔离 PostgreSQL、四视口浏览器和客观保音高探针验证。本轮再复查没有发现新的 P0/P1 主链阻断，但部署前仍需收敛以下风险：

1. 脚本复核页直接显示 `high` / `medium` / `low` / `unknown`，与其余作者界面的中文口径不一致。
2. Edition 聚合投影短暂偏差已有“重读后收敛”用例，但缺少永不收敛、延迟期取消、真实 scope/身份不匹配绝不重试的明确边界测试。
3. 新请求的作者标识已收敛为 `owner`，本计划首轮只读快照观察到长期数据库有 18 条 `explicit_generation_actor='local-owner'` 历史请求。该数量不是不变量，`TTS49-G0` 必须重新只读计数；当前源码读路径兼容，但尚缺一条专门的旧数据回归证据。
4. 初次复查快照中，工作树同时包含计划 44、45、47 与验收证据：89 个已跟踪文件有改动，并有 75 个未跟踪文件。本文档编写期间又出现了独立的人物卡计划 48，因此数量只是历史快照；`TTS49-G0` 必须重新冻结实际清单，并将计划 48 视为本任务的无关现有改动。

两项现有真实验收门禁不因本计划改变：

- `TTS47-UX-FINAL=HOLD_AUTHOR_LISTENING`：仍需作者完成真实章节听感验收。
- `TTS47-CAST-FINAL=HOLD_BROWSER_MODEL_PROVIDER`：仍需真实 `ai-novel-writer` Provider 完成一次整书智能选角成功浏览器全链。

### V1.1 二次复查修订

1. 前端 `package.json` 位于仓库根目录，`frontend/` 下没有独立 manifest；删除不可执行的 `pnpm --dir frontend` 命令。
2. 当前 shell 没有裸 `node`；施工必须先通过工作区依赖定位并冻结 Node `24.19.0` 与 pnpm `11.19.0` 的实际路径。
3. 源码当前唯一 Alembic head 是 `20260901_0036`，但两个脚本复核 PostgreSQL 测试仍锁死 `20260829_0034`；本计划改为使用仓库当前唯一 head 校验测试库，不修改任何迁移。
4. 旧 actor 成功链必须新增 HTTP `PATCH → approve → Edition` 回归；只做 store/backend 测试不足以证明当前页面调用链。
5. actor 是封印后的非空审计标识，不是 `owner | local-owner` 二值枚举；安全回归改为“持久化后修改 actor 被数据库封印拒绝”与“action/provenance 账本不一致时拒绝继承”，不按字符串名称猜测攻击者。

## 二、目标、完成口径与非目标

### 1. `TTS49-CODE-FINAL`

必须同时满足：

- 脚本复核页的置信度仅显示稳定中文标签，前后端协议值不变。
- Edition 聚合投影重试在次数、时间、取消和不可重试错误上全部有 fail-closed 回归。
- 旧 `local-owner` 请求能继续复核、冻结、生成 Edition，并能在精确证据一致时被新 `owner` 请求继承人工修正。
- 不新增迁移、不改公共 API/DTO、不改写历史 actor 字段。

### 2. `TTS49-RELEASE-AUDIT`

必须同时满足：

- 对计划 44、45、47、49 的已跟踪及未跟踪文件逐项归类，并把独立计划 48 明确标记为本任务不得暂存的无关改动。
- 证明候选范围不包含构建产物、缓存、数据库 dump、临时文件、密钥或无关用户改动。
- 分别列出“可进入候选提交”、“必须保留但不应混入”和“需先裁决”的文件，但本计划不自动暂存、提交或推送。

### 3. 非目标

- 不重写已通过验收的声音配置器、选角求解器或播放器。
- 不在本计划中引入场景情绪控制、新能力键、`0037` 迁移或新模型依赖。
- 不回填或批量归一历史 `local-owner` 记录。
- 不使用长期数据库进行写入型测试，不改动真实小说、声音绑定或媒体。
- 不宣称本计划通过即代表计划 47 的两项真人/真模型门禁已通过。

## 三、冻结修复方案

### 1. 置信度本地化

保留协议枚举 `high | medium | low | unknown`，仅在前端显示层转换：

| 协议值 | 界面文案 |
| --- | --- |
| `high` | `高` |
| `medium` | `中` |
| `low` | `低` |
| `unknown` | `未知` |

实现要求：

- 使用唯一穷尽映射，界面统一为“置信度：高”等作者语言。
- 不复制 DTO，不把中文文案写回数据库或 API。
- 回归四种值，并断言页面不再渲染英文原值。

### 2. Edition 投影重试边界

生产语义继续保持：只有可识别的 Edition 聚合投影短暂偏差允许有界重读；真实 novel/document/revision/manifest scope 或身份不匹配必须立即失败。

新增回归矩阵：

1. 偏差在限额内收敛：已有用例继续通过，仅构建一个播放运行时。
2. 持续偏差达到 `maxPollAttempts`：返回稳定合同错误，请求次数等于上限，不向 bridge 发布 Edition，不安装 bundle，不创建播放器。
3. 持续偏差达到 `pollTimeoutMs`：在有界时间内失败，不无限循环，不继续后台请求。
4. 在 backoff/延迟期取消或被新 load 取代：以 `AbortError`/已取消语义结束，不发起后续请求，不留残留运行时。
5. 真实 scope/身份不匹配：首次立即 fail closed，延迟和重读调用次数均为零。

测试优先注入可控 `now` 和 `delay`，不使用真实 sleep。只有测试证明现有实现不满足冻结语义时，才允许对 `chapter-narration-session.ts` 做最小修正。

### 3. 旧 actor 兼容

冻结原则：

- `LOCAL_OWNER_ACTOR_ID = "owner"` 继续仅用于新的章节朗读请求和脚本复核审计动作；不对官方音色选择、隐私同意、删除等其他子系统执行全局 `local-owner → owner` 替换。
- actor 是最长 120 字符的非空审计标识，不是业务枚举；合法历史值不因名称不同而失效。
- 请求幂等重放继续使用该历史请求已保存的 `explicit_generation_actor`，不重写它。
- 审核和冻结依据固定本地 owner scope、非空显式意图、CAS 和不可变证据；不以数据库早期字符串的表面不同否定合法本地作者。
- 人工修正的跨请求继承仍必须同时满足源脚本批准、源段落哈希、前后锚点、说话人目标、工作区和审计账本一致；任一证据漂移必须 fail closed。

隔离回归至少覆盖：

1. 一条 `explicit_generation_actor='local-owner'` 的 `review_required` 历史请求，通过与当前页面相同的 HTTP `PATCH → approve → request GET` 完成段落修正、作者冻结和 Edition 创建。
2. 相同幂等键重放返回原结果，不重写历史 actor，不重复生成子版本、审计动作或 Edition。
3. 新 `owner` 请求只在精确符合继承规则时继承上述历史请求中已批准的人工修正。
4. 已持久化请求的 `explicit_generation_actor` 被 SQL 尝试修改时，必须由现有数据库封印触发器拒绝，原值保持不变。
5. action/provenance 的 actor 账本不一致、不同 novel/workspace、锚点或说话人目标变化时拒绝继承，不产生新 Edition。

### 4. PostgreSQL 当前 head 门禁

- `tests/narration/test_script_review_backend_postgres.py` 和 `tests/narration/test_script_review_postgres.py` 不再写死 `EXPECTED_HEAD = "20260829_0034"`。
- 测试使用 `ScriptDirectory` 读取仓库唯一 Alembic head；多 head 直接失败，隔离数据库 `alembic_version` 必须与该唯一 head 精确一致。
- 当前已核实的唯一 head 为 `20260901_0036`；施工时若 head 再变化，`TTS49-G0` 重新冻结，不把历史数字常量再复制到测试中。
- 只修改测试的库身份门禁；不改已执行迁移、ORM、schema sentinel 或生产 readiness。

## 四、文件所有权与改动边界

### 允许修改

- `frontend/src/narration/script-review-panel.ts`
- `frontend/src/narration/script-review-panel.test.ts`
- `frontend/src/narration/chapter-narration-session.test.ts`
- `frontend/src/narration/chapter-narration-session.ts`：仅当新边界测试证明现有生产逻辑有缺陷时才允许最小修正。
- `tests/narration/test_script_review_actions.py`
- `tests/narration/test_script_backend.py`
- `tests/narration/test_script_review_http_continue.py`
- `tests/narration/test_script_review_backend_postgres.py`
- `tests/narration/test_script_review_postgres.py`：仅允许修正当前唯一 Alembic head 的测试库门禁。
- `tests/narration/test_edition_service.py`
- `docs/开发文档/证据/计划49/`

### 禁止触碰

- `backend/models.py`、`backend/migrations/**`、公共 API/DTO 和 capabilities 契约。
- 选角求解器、VoiceGenerator、Nano Sidecar、私人音色删除与媒体存储链。
- QwenPaw 上游核心代码、长期数据库、真实小说、声音绑定和媒体。
- 与计划 49 无关的现有用户改动。

如回归暴露需要修改禁止范围内的契约、迁移或数据语义，必须停止扩张施工，记录新阻断并请用户重新裁决。

## 五、施工波次与子代理并行设计

### 本任务不并行

本计划不派发子代理。理由是三项改动都很小，但共用同一组前端会话测试、脚本审核 fixture 和发布范围判断；并行修改的冲突、重复建模和汇合风险高于节省的时间。主代理是唯一实现与集成责任人。

| 波次 | 工作包 | 标记 | 目标与退出门禁 |
| --- | --- | --- | --- |
| W0 | `TTS49-G0` | `GATE/SER/MUTEX` | 冻结 Git 状态、当前唯一迁移 head、工作区 Node/pnpm 实际路径与版本、长期 bundle 身份和计划 44/45/47/48/49 文件归属；计划 48 保留但不进入本任务，发现无法分离的无关改动则停止。 |
| W1 | `TTS49-FE-I18N` | `SER/MUTEX` | 实施穷尽置信度映射及四值测试；定向 Vitest 通过才能退出。 |
| W2 | `TTS49-RETRY-QA` | `SER/MUTEX` | 先只增加边界测试；若现有代码失败，仅修正被证明的最小缺陷。 |
| W3 | `TTS49-LEGACY-ACTOR` | `SER/MUTEX` | 用 HTTP fixture 与当前唯一 head 的隔离 PostgreSQL 完成旧 actor 成功、幂等、继承、持久封印和账本漂移拒绝矩阵。 |
| W4 | `TTS49-RELEASE-AUDIT` | `GATE/SER/MUTEX` | 生成发布范围报告，排除生成物、秘密和无关改动；不执行 Git 写入。 |
| W5 | `TTS49-QA` | `GATE/SER` | 定向、全量、打包、Compose、diff 和必要的隔离浏览器回归全部通过。 |
| W6 | `TTS49-FINAL` | `INT/GATE/SER` | 主代理复核 diff、证据、冗余和未闭合门禁，分别裁决 CODE 与 RELEASE-AUDIT。 |

共享锁：`LOCK-NARRATION-FE`、`LOCK-NARRATION-REQUESTS`、`LOCK-POSTGRES-TEST`、`LOCK-DOC-INDEX`、`LOCK-GIT`。

汇合顺序固定为：G0 → 置信度 → 重试边界 → 旧 actor 回归 → 范围审计 → 全量验证 → 最终裁决。

## 六、测试、真实验收与证据

### 1. 定向自动化

```text
# 当前已核实路径；G0 必须用工作区依赖结果重新冻结，不假定裸 node 可用。
PATH=/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback:$PATH \
  pnpm exec vitest run \
  frontend/src/narration/script-review-panel.test.ts \
  frontend/src/narration/chapter-narration-session.test.ts

.venv/bin/python -m pytest \
  tests/narration/test_script_review.py \
  tests/narration/test_script_review_actions.py \
  tests/narration/test_script_backend.py \
  tests/narration/test_script_review_http_continue.py \
  tests/narration/test_edition_service.py
```

PostgreSQL 回归必须显式使用隔离 `TTS_TEST_DATABASE_URL`：数据库名固定为 `ai_novel_world_2026_tts_test`，用户为 `tts_test`，主机必须是 loopback，并且不得与 `AI_NOVEL_DATABASE_URL` 指向同一数据库。先在不打印 URL/口令的前提下调用现有精确身份预检，再升级该一次性数据库到仓库当前唯一 head：

```text
TTS_TEST_DATABASE_URL="$TTS_TEST_DATABASE_URL" \
  .venv/bin/python -c \
  'from tests.narration.test_script_review_backend_postgres import _live_url; _live_url()'

AI_NOVEL_DATABASE_URL="$TTS_TEST_DATABASE_URL" \
  .venv/bin/python scripts/migrate.py upgrade head

TTS_TEST_DATABASE_URL="$TTS_TEST_DATABASE_URL" \
  .venv/bin/python -m pytest \
  tests/narration/test_script_review_backend_postgres.py \
  tests/narration/test_script_review_postgres.py
```

不 `export` 测试 URL，不得使用长期数据库，不运行会拥有或删除其他数据库的破坏性请求封印模块。

### 2. 全量门禁

```text
env -u TTS_TEST_DATABASE_URL -u TTS_VOICE_DELETION_TEST_DATABASE_URL \
  .venv/bin/python -m pytest
PATH=/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback:$PATH pnpm test
PATH=/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback:$PATH pnpm typecheck
PATH=/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback:$PATH pnpm build
.venv/bin/python scripts/package_plugin.py
.venv/bin/python -m pytest \
  tests/test_manifest.py \
  tests/test_skill_contract.py \
  tests/test_qwenpaw_integration_contract.py
PATH=/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback:$PATH \
  node --test scripts/tts/controller-node/test/*.test.mjs
docker compose config --quiet
git diff --check
```

全量 pytest 显式撤销可选 PostgreSQL 环境变量，避免意外激活其他拥有不同数据库生命周期的可选模块；本计划的真实 PostgreSQL 证据由上一个精确命令单独提供。

### 3. 隔离浏览器

如实施包含置信度 UI 变更，使用隔离 QwenPaw 与隔离数据库复验 `1920×1080` 和 `390×844`：

- 四种置信度不显示英文枚举。
- 脚本冻结前后的操作区、焦点与滚动不回归。
- 不恢复已删除的重复筛选、重复绑定或重复保存控件。
- 控制台无本轮新增 error/warning。

旧 actor 和 Edition 投影边界只用隔离 fixture/测试数据验证，不用长期小说构造故障。

### 4. 证据

施工时新建：

- `docs/开发文档/证据/计划49/README.md`
- `docs/开发文档/证据/计划49/TTS49-RELEASE-SCOPE.md`

证据必须分开记录自动化、隔离数据库、浏览器、未执行项和现有计划 47 门禁，不用新截图改写历史验收记录。

## 七、发布范围审计与后续授权

`TTS49-RELEASE-SCOPE.md` 至少包含：

1. 基线 commit、分支、迁移 head、候选 bundle hash 和长期 bundle hash。
2. 已跟踪 diff 与未跟踪文件清单，按计划 44/45/47/49、共享集成、证据和无关项分类；计划 48 单独列入“保留但不暂存”。
3. 生成物、缓存、dump、临时日志、调试截图和可能秘密扫描结果。
4. 迁移、前端 bundle、插件包与验收证据之间的一致性。
5. 不同计划无法原子分离的共享文件及原因，以及提交前必须的裁决。

本计划文本不授权 Git 提交、推送、长期数据库迁移、PawApp 安装或重启。只有范围审计和全量门禁通过后，才能由用户分别授权后续动作。

## 八、恢复与失败处理

- 本计划不增加 schema 或业务数据写入，因此代码回退不需要数据库降级。
- 置信度映射回归时可单独回退显示层，协议和历史记录不受影响。
- 重试边界回归时优先 fail closed，不回退到无限重试或变调播放。
- 旧 actor 回归如失败，禁止通过长期批量回填规避；先保持长期环境未部署，记录确切失效路径并重新裁决兼容方案。
- 范围审计无法证明候选文件归属时，保留现有工作树，不 stash、不删除、不暂存、不提交。

## 九、最终验收清单

- [ ] 四种置信度全部显示中文，协议值不变。
- [ ] 收敛、次数耗尽、超时、取消和不可重试错误全部有精确断言。
- [ ] 所有失败路径都不向 bridge 发布 Edition、不安装 bundle、不创建播放器、不继续请求。
- [ ] 旧 `local-owner` 请求成功完成修正、冻结、Edition 创建和幂等重放。
- [ ] 新 `owner` 请求的人工继承同时覆盖成功与 action/provenance 账本漂移拒绝。
- [ ] 持久化 actor 的 SQL 修改被封印触发器拒绝；其他子系统的合法 `local-owner` 常量未被全局替换。
- [ ] 两个脚本复核 PostgreSQL 模块在仓库当前唯一 Alembic head 运行，不再锁死 `0034`。
- [ ] 无迁移、无长期写入、无公共契约漂移。
- [ ] 定向、全量、打包、Compose 和 `git diff --check` 全部通过。
- [ ] 发布范围报告能逐项解释候选文件，不包含秘密、生成物或无关改动。
- [ ] `TTS47-UX-FINAL` 和 `TTS47-CAST-FINAL` 仍按真实证据独立裁决，不被本计划“代通过”。

## 十、计划自查结论

本计划已逐项复核：

- 将两项 P2 缺口、旧 actor 兼容和混合工作树风险分成独立退出门禁。
- 没有为了测试便利而更改协议、迁移或历史数据。
- 没有把已通过的页面和播放链再次重写，也没有提前引入场景演绎范围。
- 明确保留作者听检和真实模型 Provider 两项未完成事实。
- 由于改动小且 fixture/共享文件紧密耦合，明确采用单一代理串行施工，不为形式并行增加冲突。
- 提交、推送和长期部署仍需在范围及验收通过后由用户单独授权。
- 编写期间发现的计划 48 编号冲突已通过将本计划顺延为 49 解决；未覆盖、重命名或改写人物卡计划。
- V1.1 已用真实仓库结构复核命令：前端从根 manifest 运行，Node/pnpm 来自工作区依赖，不再保留不存在的 `frontend/package.json` 假设。
- V1.1 已将 PostgreSQL 旧 head、HTTP 全链缺口和 actor 语义歧义转化为精确文件所有权、测试命令和退出断言。
- 修订后的前端定向命令已实际运行，结果为 `2 files / 50 tests passed`；这只证明命令和当前基线可执行，不代表计划 49 已施工。

终审裁决：**方案边界清晰、风险可恢复，具备等待批准施工的条件；当前不应开始部署或 Git 操作。**
