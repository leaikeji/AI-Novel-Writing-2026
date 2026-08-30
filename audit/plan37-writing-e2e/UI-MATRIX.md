# 计划 37 非 TTS 写作 UI 三视口验收矩阵

状态：**2026-08-30 候选包已安装并完成非 TTS 三章及三视口复验；连续正文为 2059、1783、2128 字，active index 收敛到 version 7。** 最终第三章工作台在 1920×1080、2560×1440、390×844 均无横向溢出，标题、字数和主要写作操作可见；未点击或验收 TTS。真实模型仍有一次复合身份语义误判，属于候选内容审阅风险，不把它表述成内容质量全通过。详细证据见 `docs/开发文档/证据/计划37/E2E37-LIVE.md`。

工作包：`E2E37-UI`（`PAR-C`）

## 1. 范围与硬边界

本矩阵只验收计划 37 的写作链路：建书、大纲人物草案、正式人物卡的基础资料／本线档案／成长与状态、章纲、正文生成与采用、模型证据、小说向量授权与同步、审稿、选区编辑。

明确排除：

- 不点击人物卡“声音”页签；
- 不打开工作台“朗读”导航；
- 不请求 TTS、Nano、VoiceGenerator、音频、播放器、私人音色或声音绑定接口；
- 不把任何 TTS 页面、自动化或运行状态纳入计划 37 的 PASS／HOLD；
- 不读取或修改真实用户小说；
- 不在浏览器控制台读取密钥、完整向量、完整查询原文或宿主私有状态；
- 不通过清理本地向量、撤销授权、删除小说或归档人物制造测试状态。

本轮准备阶段禁止浏览器交互。后续正式执行时，所有写动作必须限定在计划 37 新建的合成实验小说及其固定素材中。若需错误态，优先使用隔离 stub／故障注入环境；不得通过破坏长期数据库、清除真实 Key 或中断其他用户任务制造失败。

## 2. 参数、入口与视口

### 2.1 固定占位参数

执行前由主代理用隔离实验数据替换：

```text
<NOVEL_ID>       计划 37 合成实验小说 ID
<CHAPTER_1_ID>   第一章 document ID
<CHAPTER_2_ID>   第二章 document ID
<CHAPTER_3_ID>   第三章 document ID
<CHARACTER_ID>   主角稳定人物根 ID（只用于网络证据核对，不进入 URL）
```

`/chat/<SESSION_ID>` 与 `/chat` 均受工作台路由支持；为保证可复现，首次打开统一使用 `/chat`，页面建立宿主会话后允许路径变成 `/chat/<SESSION_ID>`，但查询参数必须保持。

### 2.2 精确入口

| 入口 | URL / query | 备注 |
| --- | --- | --- |
| 创作中心 | `http://127.0.0.1:18088/chat?novel_center=1` | 建书入口；页面标题“创作中心” |
| 全局向量模型接入 | `http://127.0.0.1:18088/chat?novel_center=1&view=embedding-settings` | 仅核对配置状态，不保存、清 Key 或测试连接 |
| 章节列表 | `http://127.0.0.1:18088/chat?novel_workbench=1&novel_id=<NOVEL_ID>` | `chapters` 是默认 section，URL 不写 `section=chapters` |
| 大纲 | `http://127.0.0.1:18088/chat?novel_workbench=1&novel_id=<NOVEL_ID>&section=outline` | 人物草案也在此入口 |
| 角色列表 | `http://127.0.0.1:18088/chat?novel_workbench=1&novel_id=<NOVEL_ID>&section=roles` | 默认角色列表视图 |
| 小说设定 | `http://127.0.0.1:18088/chat?novel_workbench=1&novel_id=<NOVEL_ID>&section=settings` | 再点击“语义索引”页签；该子页签不写入 query |
| 第一章正文 | `http://127.0.0.1:18088/chat?novel_workbench=1&novel_id=<NOVEL_ID>&document_id=<CHAPTER_1_ID>` | 第二、三章替换 document ID |

### 2.3 固定视口

每个核心成功态至少在以下三档各截一张；移动端交互态不得仅用缩放后的桌面截图代替。

| 视口键 | CSS viewport | 截图后缀 |
| --- | --- | --- |
| `desktop-1920` | `1920×1080` | `1920x1080` |
| `desktop-2560` | `2560×1440` | `2560x1440` |
| `mobile-390` | `390×844` | `390x844` |

统一截图格式：

```text
audit/plan37-writing-e2e/screenshots/<序号>-<场景>-<状态>-<视口>.png
```

例如：

```text
01-create-novel-step-idea-390x844.png
03-character-workspace-growth-1920x1080.png
06-body-generation-history-model-evidence-2560x1440.png
```

失败态另加 `-error`，键盘证据另加 `-keyboard`，焦点证据另加 `-focus`。截图不得包含 API Key、完整私有素材、完整查询文本或其他小说内容。

## 3. 通用验收规则

每个场景至少检查：

1. 页面没有横向溢出；可滚动区域不会把主操作按钮永久挡住。
2. 页面缩窄后正文、卡片、弹窗和错误文案不重叠、不截断关键含义。
3. `Tab` 可到达主操作；焦点环可见；被禁用操作不可获得误导性激活结果。
4. 弹窗打开后焦点位于弹窗内；关闭后回到合理触发点。人物卡页签用 `←/→` 切换，`aria-selected` 与可见面板一致。
5. `Esc` 行为遵循组件契约：人物卡有未保存修改时必须先显示确认；明确设置 `keyboard: false` 的建书向导不得被 Esc 意外关闭。
6. `role="alert"`／`aria-live` 的错误或进度可被观察；错误发生后作者输入、草案和正式正文不得静默消失。
7. 成功、失败、重试和等待状态不能只靠颜色区分。
8. 浏览器网络证据只记录端点、method、HTTP 状态、request ID／任务 ID 和脱敏摘要；不保存请求正文、Key、向量或完整素材。
9. 每次准备离开含未保存修改的页面或弹窗时，验证明确提示或现有自动保存契约，不把静默丢稿当成通过。
10. 页面出现“朗读”“声音”不等于需要点击；整个执行期间 narration/TTS 请求计数必须为 0。

每个视口记录以下几何值：

```text
window.innerWidth / window.innerHeight
document.documentElement.scrollWidth / clientWidth
目标弹窗 rect（x/y/width/height）
主滚动容器 scrollHeight / clientHeight
当前 focus 的 role/name 或稳定 selector
```

## 4. 三视口执行矩阵

表中“写入边界”是后续正式验收允许发生的最大写范围，不代表本次模板编写已执行该动作。

### UI-01 建书与进入大纲

| 项目 | 内容 |
| --- | --- |
| 入口 | `/chat?novel_center=1` |
| 前置 | 隔离实验库；允许创建且只创建计划 37 合成小说 |
| 稳定节点／文案 | `main.mb-center-page`；标题“创作中心”；按钮“创建新小说”或 `.mb-new-novel-tile` 文案“新建”；弹窗 `.mb-create-modal` 标题“创建新小说”；步骤文案“选择创作类型”“选择小说受众”“创作思路”；完成态“创建成功！”与“立即创建大纲” |
| 正常动作 | 键盘打开向导；选择“长篇小说”和受众；填写固定合成思路、模板、书名和非敏感封面路径；完成创建；点击“立即创建大纲” |
| 写入边界 | 仅建书 draft、该合成小说及建书完成事务；不得删除现有小说，不使用 AI 取名或 AI 封面来扩大真实调用次数 |
| 键盘／焦点 | Tab 顺序覆盖选择卡、下一步、上一步与最终完成；禁用的“下一步”不可提交；向导 `keyboard:false`，Esc 不应丢失建书草稿；窄屏底部操作可达 |
| 错误／重试 | 使用隔离 stub 令一次保存失败，观察错误 Alert 和已填表单仍在；恢复后重试同一步，不应重复创建小说 |
| 截图 | `01-create-novel-idea-*`、`01-create-novel-success-*`、`01-create-novel-error-*` |

### UI-02 大纲与人物草案

| 项目 | 内容 |
| --- | --- |
| 入口 | `/chat?novel_workbench=1&novel_id=<NOVEL_ID>&section=outline` |
| 稳定节点／文案 | `.mb-outline-workspace`；`[aria-label="大纲生成步骤"]`；步骤“章节／背景／人物草案／情节／亮点”；当前步 `aria-current="step"`；人物步标题“人物草案”；说明“这里只做创作规划；完成大纲后统一进入正式人物卡”；按钮“生成人物草案”“跳过 AI，直接填写人物草案”“完成大纲” |
| 正常动作 | 人工填写章节数；背景、人物、情节、亮点使用固定 stub 候选或人工输入；进入人物草案，新增主角与配角；完成正式化 |
| 写入边界 | 仅当前小说 outline draft、正式 outline/setting revision、人物根、主线默认人物实例及 profile revision；失败候选不得修改正式人物 |
| 人物草案弹窗 | `.mb-character-modal`；标题“新增人物草案”／“修改人物草案”；字段“姓名、性别、年龄、性格、身份、核心目标、人物小传”；按钮“保存修改” |
| 同名冲突 | 结构化冲突显示“系统不会按姓名自动合并”；必须可选择“关联现有人物”或“改名后新建”；未选择前不得完成正式化 |
| 键盘／焦点 | 顶部步骤按钮可聚焦；不可达步骤保持 disabled；人物弹窗可完整 Tab；关闭后焦点回到对应人物 pill 或“新增”；滚动时底部“下一步／完成大纲”可达 |
| 错误／重试 | 人物 AI 失败显示“生成…失败，原内容已保留”类错误；原背景、版本、人工草案仍在；随后可用“跳过 AI”继续。已有草案点“重新生成”先出现替换确认 |
| 未保存 | 修改人物草案后取消弹窗时记录当前实现行为；若无离开确认，必须证明草案未被当作已保存并把风险列入缺陷，不得误记 PASS |
| 截图 | `02-outline-character-draft-*`、`02-outline-character-link-required-*`、`02-outline-generation-error-*` |

### UI-03 正式人物卡（排除声音）

| 项目 | 内容 |
| --- | --- |
| 入口 | `/chat?novel_workbench=1&novel_id=<NOVEL_ID>&section=roles` |
| 稳定节点／文案 | 导航“角色”；子页“角色列表”；`.mb-role-card-main`；弹窗 `[role="dialog"].anw-character-workspace-dialog`；`[role="tablist"][aria-label="人物卡栏目"]` |
| 允许页签 | “基础资料”“本线档案”“成长与状态” |
| 禁止页签 | **“声音”不得点击、聚焦激活或截图，不验收其内容。** 键盘页签检查到“成长与状态”即停止；不得用方向键继续进入“声音” |
| 基础资料观察 | “人物姓名、角色定位、性别、核心主题、公共小传”；“称谓与别名”；“引用概览” |
| 本线档案观察 | “现实身份、真实身份、掩护身份、出生年、出生历法、出生信息、开篇年龄说明、职业、初始性格、目标、缺陷、秘密、成长方向” |
| 成长状态观察 | 面板 `aria-label="成长与状态，只读"`；说明“以下内容由已确认故事事实投影生成，不能在人物卡中直接改写。”；空态“截至当前叙事位置，尚无已确认的成长状态。”或事实卡与“故事序位” |
| 正常动作 | 修改一次基础资料和一次本线档案并保存；正文同步 StoryFact 后重新打开成长页，核对状态与来源；改名后角色卡 ID 对应关系保持不变 |
| 写入边界 | 只允许人物根 PUT、所选主线实例 profile PUT；成长面板严格只读；不得修改或创建声音绑定 |
| 单／多线 | 单线不得显示时间线／人物版本选择器。多线样例仅验证打开前必须显式选择，选择器文案“时间线”“人物版本”；不得猜最近使用值 |
| 键盘／焦点 | Tab 打开人物卡；页签支持 `←/→` 且 `aria-selected` 同步；保存错误自动切换到相应页签并聚焦字段；关闭后焦点回角色卡 |
| 未保存／CAS | 修改后显示“有未保存修改”；点“关闭”或 Esc 必须询问“人物卡尚有未保存修改，确定离开吗？”；CAS 冲突显示“人物卡已在其他位置更新”，保留输入并提供“定位到需要处理的字段” |
| 滚动 | 900px 桌面弹窗正文区独立滚动，摘要头与底部保存区可用；390×844 为全屏，不能出现横向滚动或遮挡“保存人物卡” |
| 截图 | `03-character-workspace-basic-*`、`03-character-workspace-line-profile-*`、`03-character-workspace-growth-*`、`03-character-workspace-unsaved-*`、`03-character-workspace-cas-error-*` |

### UI-04 新建章节与章纲

| 项目 | 内容 |
| --- | --- |
| 入口 | `/chat?novel_workbench=1&novel_id=<NOVEL_ID>` |
| 稳定节点／文案 | 标题“章节列表”；按钮“新建章节”；弹窗 `.mb-chapter-wizard-modal` 标题“创建新章节”；六步“线索、角色、伏笔、期望剧情、章节大纲、完成” |
| 正常动作 | 选择固定故事线、人物、伏笔；填写期望；目标字数设为 2000；使用 stub 生成章纲；核对“章节大纲已生成”；“确认创建章节” |
| 写入边界 | 仅合成小说的 chapter draft、ChapterBrief 和 document；本 UI 专项不使用“AI智能推荐线路”，避免额外模型动作 |
| 模型证据观察 | 生成态“<当前任务模型> 正在创作章节大纲...”及结果“任务模型：…”；若为 `not_exposed`，必须显示“宿主未公开实际模型；任务前后有效模型一致（…）”，不得写“实际模型已验证” |
| 键盘／焦点 | 选择卡可由键盘激活；步骤内返回/下一步顺序稳定；弹窗滚动不丢失当前字段；结果页的章节标题、章纲和三个操作按钮可达 |
| 错误／重试 | stub 返回一次生成失败，错误可见且期望、人物、伏笔选择仍保留；恢复后点击“生成章节大纲”或“重新生成”；不得重复创建章节 |
| 未保存 | 章纲生成后修改标题或章纲、返回上一步再回来，核对草稿保留；关闭向导若当前无明确确认，需要记录为风险并确认服务端 draft 可恢复 |
| 截图 | `04-chapter-wizard-expectation-*`、`04-chapter-outline-ready-*`、`04-chapter-outline-error-*` |

### UI-05 章纲编辑与正文空态

| 项目 | 内容 |
| --- | --- |
| 入口 | `/chat?novel_workbench=1&novel_id=<NOVEL_ID>&document_id=<CHAPTER_N_ID>` |
| 稳定节点／文案 | 标题 `<章节标题>`；正文空态 `[aria-label="章节正文空状态"]`；“暂无章节内容”“生成章节内容”“我已有正文，点击直接填写”；工作流按钮“生成正文”“修改章纲”“同步进展”“历史” |
| 章纲弹窗 | `.anw-outline-edit-modal`；标题“编辑章纲”；字段 `aria-label="章节大纲"`、`aria-label="目标字数"`；按钮“取消”“保存章纲” |
| 正常动作 | 打开章纲，核对目标 2000 和固定约束；修改一个非关键字段并保存；状态应显示“章纲已保存” |
| 写入边界 | 仅当前 ChapterBrief 版本；不得生成正文或同步事实，直到 UI-06 |
| 键盘／焦点 | 打开后焦点留在弹窗范围；正文区/章纲可滚动；关闭后由 `focusTriggerAfterClose:false` 配合显式恢复到“修改章纲”触发按钮 |
| 未保存 | 修改章纲后点“取消”，重新打开应恢复最近已保存版本而非把未保存值冒充正式值；选择编辑任务应用到章纲时先出现“尚未保存”，随后必须手工“保存章纲” |
| 错误／重试 | 隔离 CAS 冲突或保存失败时弹窗保持打开、文本不丢失，错误可见；刷新基线后重试 |
| 截图 | `05-chapter-empty-*`、`05-chapter-brief-*`、`05-chapter-brief-save-error-*` |

### UI-06 正文生成、采用与模型证据

| 项目 | 内容 |
| --- | --- |
| 入口 | 每章 `/chat?novel_workbench=1&novel_id=<NOVEL_ID>&document_id=<CHAPTER_N_ID>` |
| 触发节点 | “生成正文”或空态“生成章节内容”；素材弹窗 `.anw-asset-modal` 标题“选择私有库配置”；确认文案“本次将使用 <provider/model>”；生成态 `[aria-label="AI 正在创作章节内容"]` |
| 成功观察 | 候选采用后编辑器出现正文；状态“<模型证据> 正文生成完成 · <字符数> 字”；正文 1700–2300 可见字符；“历史”弹窗标题“生成历史（共 N 次）” |
| 采用语义 | 当前实现正文生成成功后由服务端候选采用接口写入 working copy/revision 路径；浏览器需核对只有合法 `ready` 候选触发采用，失败任务不改变正文 hash/revision |
| 模型证据 | 历史卡成功态显示 `verifiedGenerationModelLabel`；`not_exposed` 必须逐字包含“宿主未公开实际模型；任务前后有效模型一致（…）”，且 UI／网络记录中的 actual provider/model 为 null；rejected 任务不可恢复/采用 |
| 写入边界 | 仅当前合成章节 generation job、candidate、adopt/revision、冻结输入快照和随后作者确认的账本；真实正文模型最多按计划主代理授权执行三次，其余均 stub |
| 键盘／焦点 | 素材卡、跳过、确定选择、确认弹窗可键盘操作；生成中不能重复触发；生成结束后回到当前章节，不丢失编辑器上下文 |
| 错误／重试 | 失败弹窗标题“章节正文生成失败”；必须含“本次没有修改正式正文。”和重新尝试说明；关闭后可再次点“生成正文”；原正文与章纲保持 |
| 滚动 | 2000 字正文编辑器在三视口纵向可达；工作流底部按钮和标题工具不遮挡；390×844 不出现左右裁切 |
| 截图 | `06-body-generating-*`、`06-body-ready-*`、`06-generation-history-model-evidence-*`、`06-body-generation-error-*` |

### UI-07 正文保存、同步进展与成长投影

| 项目 | 内容 |
| --- | --- |
| 入口 | 当前章节 URL；随后角色入口 `/chat?novel_workbench=1&novel_id=<NOVEL_ID>&section=roles` |
| 稳定节点／文案 | 正文编辑器 `aria-label="<章节标题>正文编辑器"`；保存状态“本地草稿”→“已保存”；按钮“同步进展”；情报窗口“本章章节情报”；空态“本章还没有情报；完成正文后点击‘同步进展’生成” |
| 正常动作 | 人工微调少量正文并等待自动保存；点击“同步进展”；确认计划 37 固定 StoryFact 候选；返回人物卡“成长与状态”查看已确认投影 |
| 写入边界 | 当前 working copy/checkpoint、intelligence proposal/item、作者确认后的 StoryFact/关系投影；未采用候选不得进入成长状态 |
| 键盘／焦点 | 正文编辑器可聚焦和选择；状态变化可观察；同步确认、情报关闭和返回角色页可键盘完成 |
| 错误／重试 | 同步失败显示“同步进展失败”，正文仍已保存且正式事实不变；再次触发后不得重复写入同一事件 |
| 未保存 | 正文出现“本地草稿”时禁止开始依赖正式 revision 的后续断言；必须等“已保存”且 checkpoint/revision 证据一致 |
| 截图 | `07-body-local-draft-*`、`07-intelligence-ready-*`、`07-character-growth-after-fact-*` |

### UI-08 小说向量授权与增量同步

| 项目 | 内容 |
| --- | --- |
| 入口 | `/chat?novel_workbench=1&novel_id=<NOVEL_ID>&section=settings`，点击“语义索引” |
| 稳定节点／文案 | `section[aria-labelledby^="anw-semantic-index-"]`；标题“语义索引”；状态 Tag；告知“章纲要求、工作稿选区和自定义指令也可能作为查询发送”；授权前“授权前不会发起云端向量请求” |
| 正常动作 | 仅在主代理确认合成小说具备 v2 授权条件后勾选告知并授权；观察 `updating` 收敛 `ready`、同步版本、待刷新来源、来源/分块/失败及各 corpus 状态；每章正式化后重复只读观察 |
| 写入边界 | 只允许当前合成小说 `novel-embedding-consent/2` 和其 V1 语料索引刷新；不授权其他小说，不启用 V2 结构化 corpus |
| v1 升级 | 若 fixture 为旧授权，必须显示“现有授权不包含写作查询，请升级告知版本”和“升级授权并启用写作检索”；未升级前自动写作仅本地降级 |
| 键盘／焦点 | 告知 checkbox 与授权按钮可键盘操作；按钮启用前必须勾选；错误操作后 alert 自动获焦；确认框焦点不逸出 |
| 错误／重试 | 加载失败显示“无法加载语义索引”与“重新加载”；部分失败显示“最近索引错误”及“重试失败批次”；只验证安全重试，不点击撤销授权或清理向量 |
| 禁止动作 | 不点击“撤销云端授权”“清理本地派生向量”“单独清理本地派生向量”；本 UI 工作包不触发真实重建 |
| 截图 | `08-semantic-consent-v2-*`、`08-semantic-updating-*`、`08-semantic-ready-*`、`08-semantic-error-retry-*` |

### UI-09 全局向量配置只读核对

| 项目 | 内容 |
| --- | --- |
| 入口 | `/chat?novel_center=1&view=embedding-settings` |
| 稳定节点／文案 | “返回创作中心”；配置页标题区；“连接配置”；“API Host / Base URL”；“向量维度”；“API Key 状态（已脱敏）”；维度显示 2048；“最近连接记录” |
| 只读动作 | 核对服务商/模型/维度/active generation/连接状态和脱敏 Key 状态；返回创作中心 |
| 禁止写入 | 不编辑 Base URL/model ID，不输入或读取 Key，不点“仅测试连接”“验证并保存配置”“清除 API Key”、candidate rebuild/evaluate/activate/rollback |
| 安全断言 | 页面不回显 Key 明文；移动端字段和值不重叠；复制页面可见文本不得出现密钥格式 |
| 错误态 | 只允许隔离 stub 返回加载错误以观察“加载向量模型配置失败。”；不得通过修改真实配置制造错误 |
| 截图 | `09-embedding-config-readonly-*`、`09-embedding-config-load-error-*` |

### UI-10 AI 审稿

| 项目 | 内容 |
| --- | --- |
| 入口 | 已有正文的章节 URL |
| 稳定节点／文案 | 章节工具 `[role="toolbar"][aria-label="章节工具"]`；按钮 `aria-label="AI 审稿"` 文案“审稿”；确认说明包含流畅、描写、人物一致性、时空因果、伏笔与重复内容；结果标题“AI审稿报告” |
| 正常动作 | 用 stub 执行审稿；观察“本章通过基础审阅”或“本章存在需要修改的问题”、摘要、原文依据和修改建议；关闭报告 |
| 模型证据 | 报告模型标签必须来自任务不可变证据；`not_exposed` 不得被 UI 前缀“实际”错误改写为已验证。若页面出现 `实际 宿主未公开…`，记录为文案缺陷而非通过 |
| 写入边界 | 只生成审稿任务/候选分析记录；不得修改正文、StoryFact 或向量 current source |
| 键盘／焦点 | 审稿确认和关闭可键盘完成；结果长列表可滚动；P0/P1/P2 不能只以颜色表达 |
| 错误／重试 | 审稿失败后正文不变，错误可见；可再次点击“审稿”；不得把失败审稿写成通过 |
| 截图 | `10-review-confirm-*`、`10-review-report-*`、`10-review-error-*` |

### UI-11 选区编辑与统一 Diff

| 项目 | 内容 |
| --- | --- |
| 入口 | 已有正文的章节 URL；选中正文编辑器中的固定非敏感段落 |
| 稳定节点／文案 | 正文编辑器 `aria-label="<章节标题>正文编辑器"`；工具条 `[data-assistant-selection-toolbar="true"]`；操作“润色、改写、扩写、缩写、增强对白、检查问题、自定义”；审阅工具栏 `[aria-label="差异审阅操作"]` |
| 自动检索矩阵 | `rewrite/expand/dialogue/review` 可按策略检索；`polish/shorten` 不触发 Dense；`custom` 只有勾选“参考全书资料（可能向已授权的向量模型发送本次选区和自定义指令）”才检索 |
| 正常动作 | 每类操作用 stub 覆盖触发矩阵；至少一次生成 Diff，逐处“接受/拒绝”，再“应用已接受修改”；观察“AI 修改已应用”并验证“撤销 AI 修改” |
| 写入边界 | 仅当前选区 generation job、review draft 和作者明确应用后的当前 working copy；不直接改正式 revision，未决定或退出时不写正文 |
| 键盘／焦点 | Esc 收起选区工具条；自定义输入自动聚焦；Diff 支持上一处/下一处、Alt+A/Alt+R、Ctrl/⌘+Enter；焦点不跳到页面背后；应用完成可撤销 |
| 错误／重试 | 失败态标题“选区编辑失败”，操作“重试／发送到助手／退出”；冲突态“内容发生冲突”，提供“复制候选／基于新稿重新生成／放弃”；原选区只读，冲突不得覆盖新稿 |
| 滚动 | 390×844 时工具条、Diff、候选摘要和底部指标均可访问；不得挡住当前修改或形成水平溢出 |
| 截图 | `11-selection-toolbar-*`、`11-selection-custom-opt-in-*`、`11-selection-diff-*`、`11-selection-failed-*`、`11-selection-conflict-*`、`11-selection-applied-undo-*` |

## 5. 跨场景连续性断言

以下断言不能由单张截图裁决，需要串联 UI、脱敏网络记录与数据库只读证据：

| ID | 操作序列 | UI 结果 | 数据／请求边界 |
| --- | --- | --- | --- |
| `X-01` | 完成大纲 → 角色列表 → 打开主角 | 草案摘要进入同一正式人物卡 | 人物根和默认实例各一个；同名不自动合并 |
| `X-02` | 第一章采用 → 索引 updating → ready → 生成第二章 | 第二章 UI 完成且检索证据可追溯 | 只召回第一章 current revision，不含第三章或兄弟线 |
| `X-03` | 第二章同步进展 → 人物成长页 | 成长页展示已确认事实或不确定/冲突说明 | 未采用 proposal 不进入投影；GET workspace 零写入 |
| `X-04` | 人物改名 → 打开三章与角色卡 | 新名显示，历史别名仍可见 | character ID、章纲引用、StoryFact、语义 source 稳定 |
| `X-05` | Dense 故障 → 正文／章纲／审稿／选区 | 写作继续并显示降级或可复核诊断 | 云端失败不得阻止写作；未授权时云端请求严格为 0 |
| `X-06` | rejected 模型证据 → 查看候选／历史 | 禁止采用或恢复 rejected 候选 | 正式正文、人物、StoryFact、索引 current source 不变 |
| `X-07` | 全程过滤网络记录 | 页面写作能力通过 | narration/TTS/voice/audio 请求数为 0 |

## 6. 焦点与滚动专表

每个目标视口执行以下最小检查：

| 表面 | 打开后焦点 | 内部键盘路径 | 关闭／完成后焦点 | 滚动断言 |
| --- | --- | --- | --- | --- |
| 建书向导 | 弹窗首个可用选择/控件 | Tab/Shift+Tab 遍历本步 | 回到“新建”或进入大纲 | footer 始终可达，背景页不横滚 |
| 人物草案 | 姓名或首字段 | Tab 到保存；错误字段可达 | 回人物 pill／新增按钮 | 390 宽字段单列，无遮挡 |
| 正式人物卡 | 标题或首个 tab | `←/→` 仅覆盖三个计划 37 页签，停止于成长页 | 回对应角色卡 | body 独立滚动，footer 可用 |
| 章节向导 | 当前步首控件 | Tab 到下一步/返回 | 新章节卡或正文页 | 步骤与操作不相互遮挡 |
| 章纲编辑 | 章节大纲字段 | Tab 到目标字数/约束/保存 | “修改章纲” | textarea 自身与 modal body 均可滚动 |
| 正文编辑器 | 编辑器正文 | 选择文本后工具条可达 | 仍回正文选区附近 | 2000 字正文纵向滚动稳定 |
| 选区 Diff | 审阅 toolbar | 上/下处与接受/拒绝快捷键 | 应用后回正文；退出恢复选区附近 | 中央单滚动，不嵌套失控 |
| 语义索引 | 标题或告知 checkbox | Tab 到授权/重试 | 返回设置页签 | 指标和 corpus 列表不横滚 |

## 7. 错误与恢复注入清单

所有错误态只在隔离 stub／测试数据库中制造。正式执行前记录 stub 名称或 request correlation ID。

| 错误 | 预期 UI | 恢复门禁 |
| --- | --- | --- |
| 建书 draft PATCH 失败 | Alert 可见，字段值保留 | 同版本重试或重新载入已保存 draft，不重复建书 |
| 大纲人物 generation 失败 | 原草案保留，可手填跳过 AI | 成功任务前不得正式化失败候选 |
| 人物 workspace CAS 冲突 | 错误留在卡内，输入保留，定位字段 | 刷新权威版本后由作者重新保存 |
| 章纲保存冲突 | 弹窗不关闭，文本保留 | 获取新 baseline 后人工裁决 |
| 正文 generation rejected/timeout | “本次没有修改正式正文” | 再次生成产生新任务，旧失败不复用 |
| 同步进展失败 | 正文已保存，事实不变 | 重试保持幂等，不重复事件 |
| 语义索引加载/部分失败 | 重新加载／重试失败批次 | active 旧索引继续服务，不清向量 |
| Dense 查询失败 | 写作继续、本地词面降级 | snapshot 记录 degraded reason |
| 审稿失败 | 报错，正文不变 | 新任务重试 |
| 选区任务失败/内容冲突 | 失败或冲突专用操作 | 不覆盖当前 working copy，可重试或退出 |

## 8. 单次执行记录模板

每一行必须填实际结果；不能用“代码中有此文案”代替浏览器通过。

| 字段 | 记录 |
| --- | --- |
| 执行时间 |  |
| commit / tree |  |
| 插件包 SHA-256 |  |
| PawApp health |  |
| migration head |  |
| 合成 novel/document IDs |  |
| 视口 |  |
| 场景 ID |  |
| URL（ID 可缩写） |  |
| 数据前置摘要 |  |
| 操作步骤 |  |
| 期望节点／文案 |  |
| 实际节点／文案 |  |
| 键盘与焦点结果 |  |
| 横向溢出 |  |
| 主滚动结果 |  |
| 写请求端点／状态（脱敏） |  |
| 模型证据状态 |  |
| Dense／lexical／degraded |  |
| TTS 请求计数（必须 0） |  |
| 截图路径 |  |
| 裁决 | `PASS / FAIL / BLOCKED / OUT_OF_SCOPE` |
| 缺陷 ID／备注 |  |

## 9. 最终证据清单

计划 37 最终三视口裁决至少应具备：

- 三档视口的建书、大纲人物草案、人物卡三个允许页签、章纲、正文成功态、生成历史模型证据、语义索引 ready、审稿报告和选区 Diff 截图；
- 至少一组桌面和一组 390×844 的错误／重试证据；
- 人物卡未保存提示、CAS 输入保留及成长只读证据；
- `not_exposed` 与 `rejected` 两种模型证据 UI 记录；
- Dense 失败后的本地降级证据；
- 三章连续 URL、revision／index version 的脱敏对照；
- narration/TTS/voice/audio 网络请求为 0 的过滤报告；
- 每个场景实际结果表和最终 PASS／HOLD 汇总。

## 10. 当前准备结论

本文件只根据以下生产源码完成入口与可观察契约审计：

```text
frontend/src/contracts.ts
frontend/src/creative-center.ts
frontend/src/workbench-route.ts
frontend/src/workbench-studio.ts
frontend/src/workbench-v2.ts
frontend/src/chapter-workflow.ts
frontend/src/characters/character-workspace.ts
frontend/src/api.ts
frontend/src/embedding/embedding-config-page.ts
frontend/src/embedding/novel-semantic-index-card.ts
frontend/src/assistant-selection-controller.ts
frontend/src/assistant-selection-toolbar.ts
frontend/src/selection-edit-review-surface.ts
```

已执行安装后真实浏览器和当次授权测试。MiniMax-M3 的第一章 2059 字、第二章 1783 字、第三章 2128 字均形成合法候选并采用；第二章使用受控重试谱系，第三章写作快照真实命中前两章 current revision，增量索引最终 version 7 ready。最终正文成功态三视口几何结果如下：

| 视口 | 实际 CSS viewport | 根宽度 | 横向溢出 | 标题／2128 字 | 写作操作 |
| --- | --- | ---: | --- | --- | --- |
| 1920×1080 | 1901×1069 | 1901 | 无 | 可见 | 审稿、情报、重新生成、修改章纲、同步进展、历史均存在 |
| 2560×1440 | 2535×1426 | 2535 | 无 | 可见 | 同上 |
| 390×844 | 386×836 | 386 | 无 | 可见 | 同上，纵向滚动可达 |

移动滚动、人物卡允许页签、向量状态、Key 脱敏、正文成功态、结构化长度重试与失败保护可裁决为通过。未执行的真实审稿、真实选区修改、键盘全矩阵、CAS 冲突和错误态继续按本矩阵记为自动化／stub 覆盖或未单独浏览器执行，不能扩大为“所有 UI 细节均通过”。本轮截图只通过受控浏览器即时查看，没有写入持久化截图文件；DOM、几何、运行和数据库脱敏证据已经保存。TTS 始终未操作。
