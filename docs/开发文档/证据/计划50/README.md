# 计划 50：章节朗读播放器 UI 减重验收证据

状态：**V1.1 自查修复已部署；长期 PawApp 的 1080p／2K 桌面复验、播毕恢复语义、详情披露语义与冗余清理通过。当前长期 schema 已由计划 53 推进至 `20260902_0037`，四角色基线和完整候选已安装。**

验收日期：2026-09-02（Asia/Shanghai）

## 1. 视觉来源与范围

- 作者选定图 2：`/Users/liujia/.codex/generated_images/01a0497e-72a6-72f0-aa25-cc7853e9bb81/exec-5be6ac56-3e46-46e6-9761-3ca8e7160da8.png`，`1586×992`，SHA-256 `65610a82e500b08638b34b57916bb07fc8fd630746a7785a6bcbdfc8860833fc`。
- 本轮只验收用户指定的桌面视口：`1920×1080`、`2560×1440`；未执行移动端验收。
- 隔离浏览器先覆盖生成中、部分可播、完整可播、失败、正文不一致、暂停、播毕及详情等状态；长期 PawApp 再覆盖真实 Edition 的加载、播放、暂停、前后句、正文高亮、倍速、音量、详情和焦点恢复。
- 未点击“更新朗读”、重新生成或失败重试，没有创建 Edition、模型任务或媒体。

## 2. 部署边界与不可变身份

V1.0 首轮部署时，完整候选的 schema head 为 `20260901_0036`，但长期数据库仍为 `20260830_0035`，且只有 `ai_novel` 角色，没有计划 49 要求的 schema owner／migrator／API／worker 四角色 ACL 基线。完整发布因此按门禁停止，没有迁移数据库、写 ACL 或安装新后端。

本轮改用前端兼容包：从部署前已安装插件复制整树，只替换最终 `frontend/dist/index.js`。QwenPaw 公开 `plugin validate` 和离线 `plugin install --force` 均通过。

| 身份 | 值 |
|---|---|
| 部署前 bundle SHA-256 | `2b01f8c282321e4954e0865135bcc5c97cc894ce12513052dfabef86996ca845` |
| 最终 bundle SHA-256 | `43b329ec9830166d598f50eb75a19cec7ef7cc52b86dbf648a903c3cc480bbcd` |
| 最终兼容包整树 SHA-256 | `ed3a1b1dfef313bf78cf539e88ac191bf8d3026055ac8d7c0dffb9ce91642c79` |
| 部署前／后非 bundle 整树 SHA-256 | `54676f2e0c8eda81e22255c4fe7134a1ca69c127f3cc458a0588eb0b573566b7` |
| 当前完整源码包整树 SHA-256（未安装） | `3e4a4545947930b2327d36624537cd40f5cae79c560a727e5eeee922b4c9af92` |
| 长期数据库 revision | `20260830_0035`，部署前后不变 |
| 长期数据库角色 | 仅 `ai_novel`，部署前后不变 |
| 长期能力线格式 | `narration-capabilities/2`，17 项 |

前端兼容器只接受完整且无重复的 v2 旧矩阵，并在内存中补入隐藏、不可操作、reason=`CHARACTER_CAST_SCHEMA_UNAVAILABLE` 的 `character_cast_planning`；缺项、重复、未知能力或夹带 v3 能力均 fail closed。正常 v3 校验行为不变。

计划 53 随后独立建立四角色基线、完成 `0035 → 0036 → 0037` 线性迁移并安装完整候选。V1.1 自查开始时及结束后的当前身份为：

| 身份 | 值 |
|---|---|
| 当前源码／长期数据库 head | `20260902_0037` |
| 四角色 | schema owner 无登录；migrator/API/worker 可登录，均存在 |
| V1.1 安装前 bundle SHA-256 | `dd5f913799efe35f2dc4512b894deee587b82d3f310f90751c4c68ea903246bf` |
| V1.1 最终／已安装 bundle SHA-256 | `f3eccfd82c741113d59f60f2658c27fa5a0bbf44a46178a522e62efeaae85685` |
| 当前能力 | `narration-capabilities/3`，`character_cast_planning` enabled |
| 选角命令／条目 | `0 / 0` |

V1.1 没有修改数据库、角色、正文、Edition、播放偏好或媒体；公开插件校验与强制安装只替换前端 bundle。

## 3. 备份与恢复

外部备份目录：

`/Users/liujia/Documents/AI小说世界2026-backups/plan50-deploy-20260902-012731`

- PostgreSQL `0035` dump SHA-256：`213868366be4a2db9ae21c71ae5127bf8417af75773b4b648538239aa671977e`；`pg_restore --list` 共 1110 行。
- 旧插件整树已保存为 `installed-plugin-before/`。
- 媒体副本和部署前清单均为 1876 个文件；部署后重新计算的内容清单 SHA-256 仍为 `c7b9301bf65d122103a5c98cb640c874958078eab558e6e4ed7fa5f5c84b4e18`。
- 完整候选和最终前端兼容包分别保存；回退只需通过 QwenPaw 公开安装命令恢复旧插件，不需要降 schema。

V1.1 外部恢复目录：

`/Users/liujia/Documents/AI小说世界2026-backups/plan50-self-audit-20260902-1434`

- `installed-plugin-before/` 保存 V1.1 安装前的完整插件。
- `frontend-fix-candidate/` 保存通过校验的 V1.1 候选。
- 两棵插件树只在 `frontend/dist/index.js` 上有差异；回退无需降 `0037`、写数据库或处理媒体。

## 4. 截图与同图对照

- [隔离 1920×1080 候选](./TTS50-PLAYER-1920x1080.png)：实际页面 CSS 可见区为 `1901×1069`。
- [隔离 2560×1440 候选](./TTS50-PLAYER-2560x1440.png)：实际页面 CSS 可见区为 `2534×1426`。
- [长期 1920×1080](./TTS50-LONGTERM-1920x1080.png)：最终已安装 bundle、真实小说和真实 Edition。
- [长期 2560×1440](./TTS50-LONGTERM-2560x1440.png)：最终已安装 bundle、真实小说和真实 Edition。
- [参考图与长期 1080p 同图对照](./TTS50-LONGTERM-COMPARISON-REFERENCE-VS-1920x1080.png)：左侧为作者选定图 2，右侧为长期 PawApp。参考图包含正文不一致提醒；长期 Edition 与正文一致，因此提醒按设计不占位。
- [V1.1 自查 1920×1080](./TTS50-SELF-AUDIT-1920x1080.png)：真实章节恢复在末句末尾，状态显示“本章播放结束”，主按钮可访问名称为“从头重新播放章节朗读”。
- [V1.1 详情 2560×1440](./TTS50-SELF-AUDIT-DETAILS-2560x1440.png)：详情以紧凑 disclosure region 展开，版本标题不重复，仍限制在中间写作区域内。

## 5. 几何与视觉结论

隔离最终测量：

| 请求视口 | 正文纸张边界 | 播放器边界 | 左差／右差 | 播放主控中心差 | 播放器与中栏底部差 |
|---|---|---|---|---|---|
| `1920×1080` | `504.981..1407.116` | `504.981..1406.993` | `0 / 0.124px` | `-0.004px` | `0.000px` |
| `2560×1440` | `575.882..2015.880` | `575.820..2015.818` | `-0.062 / 0.062px` | `-0.000px` | `0.000px` |

长期页面再次确认：

- 播放器是 `.anw-editor-content.has-chapter-narration` 的直接内容，只占中间写作区域；没有侵入章节目录或右侧助手。
- 左区只显示当前朗读角色“旁白”；不显示正文摘录、preset、UUID 或角色类型。
- 中区的上一句／播放／下一句保持几何居中；右区紧凑排列时间、倍速、音量和“更多”。
- 正文高亮是当前内容的唯一视觉表达。朗读与正文一致时没有空白提醒带；隔离不一致状态显示唯一提醒和唯一“更新朗读”。
- 默认层没有旧状态网格、第二组时间/句数、全章 100%、冻结声音数量或重复关闭入口。

## 6. 真人交互、缺陷与修复

长期真实章节复验结果：

- 点击播放后按钮变为“暂停章节朗读”，真实音频连续推进，编辑器出现且只出现一个 `data-narration-current=true` 高亮。
- 暂停后按钮恢复“播放章节朗读”；上一句把 ordinal 从 93 调到 92，下一句回到 93。
- 倍速从 `1.5×` 切到 `1×` 后可恢复 `1.5×`；音量浮层打开、关闭和焦点返回正常。
- 首轮长期验收发现 `[P2]`：详情展开时焦点仍在“关闭朗读详情”触发按钮，Escape 不会冒泡到详情区域。已把详情和音量的 Escape 处理收口到播放器根层，删除两处重复局部处理器；最终从触发按钮或浮层内部按 Escape 均关闭，并把焦点恢复到对应按钮。
- 最终 bundle 重新安装后再次执行播放／暂停和正文高亮烟雾测试；控制台 warning/error 均为 0。
- 验收前播放位置为 ordinal 80、offset 6320ms、合法起点 80、倍速 1500。验收后使用公开播放进度 API 和备份 CAS 证据精确恢复；页面刷新后重新显示“81 / 117 句 · 上次停在第 81 段”和 `5:50 / 8:18`。

V1.1 自查新增发现与修复：

- `[P1]` 页面刷新后，恢复位置位于末句末尾但内存态 `durationMs=0` 时仍显示普通“播放”和“上次停在第 117 段”。现统一使用 `chapterPlaybackHasEnded()`，以同一 Edition Manifest 的末段时长作恢复兜底；面板文案、按钮和实际起播位置均从头重播。
- `[P2]` 详情被标成 dialog/`aria-haspopup=dialog`，但产品行为是锚定播放器的非模态披露层且没有对话框焦点圈定。现修正为 `aria-expanded`/`aria-controls` 控制的命名 `region`，Escape 与焦点恢复行为保持。
- `[P2]` 展开详情同时出现标题“朗读版本”和选择器自身的同名标签。现删除第二个可见标题及其死样式，只保留唯一版本入口。
- 修复后只读打开/关闭详情和音量，不触发播放，不写回进度；控制台 warning/error 为 0。

## 7. 自动化与构建

```text
pnpm test
  137 test files passed
  1171 tests passed

pnpm typecheck
  passed

pnpm build
  passed

.venv/bin/python scripts/package_plugin.py
  passed

.venv/bin/python -m pytest tests/test_manifest.py tests/test_skill_contract.py tests/test_qwenpaw_integration_contract.py
  136 passed

docker compose config --quiet
  passed

git diff --check
  passed
```

覆盖包括：三段式 DOM、角色原子更新、无正文摘录、无稳定 UUID、正文不一致提醒、生成失败兜底、上一句／下一句、倍速、音量、统一 Escape、播毕重播、暂停恢复、末句末尾重播、v2 能力兼容、无效位置 fail closed 及旧观察器安全字段。

## 8. 运行态复核

- PawApp health=`ready`，数据库连接为 true。
- Narration lifecycle=`ready`，Sidecar reachable=true，production worker running=true。
- 当前 bundle SHA-256 与最终兼容包一致。
- 已安装插件除 bundle 外的整树 hash 与部署前备份一致。
- 数据库仍为 `0035`，角色仍只有 `ai_novel`；没有 `0036` 选角表或整书选角能力上线。
- 媒体文件数量和内容 hash 不变；没有新增或删除媒体。

上述两行是 V1.0 首轮部署后的历史状态。V1.1 最终只读复核为：数据库 `20260902_0037`；四角色均已存在；PawApp health=`ready`；Narration lifecycle=`ready`；Sidecar reachable=true；production worker running=true；`character_cast_planning` enabled；选角命令/条目 `0/0`。这些后端变化来自计划 53，不是 V1.1 播放器安装写入。

## 9. 最终裁决

`TTS50-DESIGN-FINAL=PASS`

`TTS50-SEMANTICS-FINAL=PASS`

`TTS50-REDUNDANCY-FINAL=PASS`

`TTS50-UI-FINAL=PASS`

`TTS50-DEPLOY=PASS_FRONTEND_ONLY_V1_1`

计划 50 V1.1 已完成。该结论只覆盖章节播放器 UI 与其播放语义；四角色／能力就绪来自计划 53，其 `0037` 历史发布身份已由[计划 54](../../54-故事账本单契约收缩与测试小说清理计划.md)的 `0038` 单契约发布取代。计划 47 的真实 Provider 整书选角成功链和作者听感仍须独立验收。

final result: passed
