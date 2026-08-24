# MOSS-TTS-Nano 多角色智能朗读产品与技术设计

状态：**产品范围已冻结；技术设计已完成 2026-08-25 审核修订，尚未实施。只批准阶段 0、ADR 和原型验证；退出阶段 0 前不得开始大规模迁移或 UI 开发。**

制定日期：2026-08-24（Asia/Shanghai）

最近修订：2026-08-25（Asia/Shanghai）

修订结论：采用“本地优先、规则优先、脚本与朗读版本分离、独立显示句段合成、Manifest 分段播放、统一持久任务底座”。运行拓扑由阶段 0 基准决定，不预先锁死为进程内、受管子进程或本机 Sidecar。

目标环境：QwenPaw 2.1.0 内的 `AI小说世界2026` PawApp；Apple Silicon M4、16 GB 内存；个人、本地优先使用。

关联文档：

- [架构边界与模型接入决策](./01-架构边界与模型接入决策.md)
- [总体架构与核心流程](./06-总体架构与核心流程.md)
- [创作工作台内容模型与关系图产品规格](./09-创作工作台内容模型与关系图产品规格.md)
- [阶段实施矩阵](./08-阶段实施矩阵.md)

## 1. 结论与产品定位

本项目新增一套本地多角色有声小说生产与阅读系统：

> 人物卡保存正式人物的专属声音；书本管理的“朗读”模块管理旁白、通用/路人音色和自动选角规则；系统把不可变正文版本解析成可复核朗读脚本，按说话人调用 MOSS-TTS-Nano 生成音频，并用句段时间轴驱动编辑器高亮和滚动。

系统中的职责必须分开：

```text
MOSS-TTS-Nano             = 单说话人发声引擎
MOSS-VoiceGenerator       = 文字描述音色设计器
人物卡                     = 正式演员档案
通用音色池                 = 群演库
自动选角规则               = 配音导演
朗读脚本                   = 可复核有声书画本
朗读版本 NarrationEdition  = 一次可复现的配音制作版本
持久任务与句段缓存          = 制作流水线
播放器与句段时间轴          = 阅读体验
```

**项目决策**：目标是实现与番茄小说公开能力同类的功能架构，不复制其私有算法、声音资产、品牌、界面文案或未公开接口，也不在首版承诺达到其多年生产数据积累形成的主观音质。

## 2. 研究结论和能力边界

### 2.1 MOSS-TTS-Nano

**已核实事实**：根据 [MOSS-TTS-Nano 官方仓库](https://github.com/OpenMOSS/MOSS-TTS-Nano)、[官方 ONNX 权重](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX)及其运行时代码，Nano 具备：

- 约 1 亿参数的轻量自回归语音生成架构；
- CPU 优先和无 PyTorch 的独立 ONNX 推理路径；
- 48 kHz 双声道音频生成；
- 内置参考音色和自定义参考音频克隆；
- 长文本按句段切分；
- 流式与非流式生成；
- CLI、Web Demo、FastAPI 演示接口、浏览器 ONNX 示例和 MLX 社区接入路径；
- 文本规范化、采样参数和随机种子配置；
- Apache 2.0 许可证。

官方仓库明确说明 ONNX CPU 版本保留参考音频克隆与实时流式解码，并报告其在 MacBook Air M4 单核可运行；官方 [Nano Reader](https://github.com/OpenMOSS/MOSS-TTS-Nano-Reader)还提供本地网页朗读和浏览器 ONNX 路径。这证明本地句段朗读具备工程基础，但不等于官方模型直接返回适合本项目的可靠逐字或跨句时间轴。

官方运行时当前只附带 6 个中文参考音色，见[官方运行时映射](https://github.com/OpenMOSS/MOSS-TTS-Nano/blob/main/moss_tts_nano_runtime.py)。它们可用于安装验证和降级试听，不能独自满足本项目约 24 个槽位的通用音色池。

Nano 原生不负责：

- 从小说正文识别说话人；
- 将人物姓名映射到项目人物卡；
- 在单个请求中原生编排多角色对话；
- 根据自由文字描述创造全新音色；
- 返回可靠的逐字时间戳；
- 提供可直接依赖的高级情绪控制 API；
- 完成有声书人工校对、缓存和版本治理。

因此 Nano 只能是最终 TTS 引擎，不能被误写成完整多角色系统。

### 2.2 MOSS-VoiceGenerator

**已核实事实**：[MOSS-VoiceGenerator 官方模型卡](https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator)说明它可以根据自由文字描述生成音色、情绪和说话风格，不要求参考录音；当前公开模型约 1.7B，权重约 4.2 GB，重点支持中英文。

**项目决策**：VoiceGenerator 只在创建或调整音色时按需运行。作者从多个候选中选择一个样音，经 Nano 克隆验证后将该样音锁定为不可变音色版本；正式章节朗读全部交给 Nano。禁止为每一句台词重新调用 VoiceGenerator，否则同一人物可能出现音色漂移。

VoiceGenerator 的公开模型卡证明了文字描述生成音色，不证明其在 M4 16 GB、MPS 或与 Nano 二次克隆组合中的速度和稳定性。相关能力在阶段 0 通过前必须显示为“实验性”，不能写成无条件可用。

### 2.3 番茄式公开方案

**已核实事实**：番茄小说的[官方 App Store 说明](https://apps.apple.com/cn/app/id1468454200)公开了多角色对话音、角色设定匹配音色和情绪表达；[字节 Leto](https://leto.bytedance.com/experience)与[火山引擎有声内容创作平台](https://www.volcengine.com/product/accp)公开展示了旁白/对白分离、人物识别、情绪预测、音色选择、发音/停顿校对和批量生成。

**技术推断**：可复核的同类生产链为：

```text
正文版本
  -> Markdown/文本切分
  -> 旁白与对白识别
  -> 正式人物/匿名人物归因
  -> 情绪、表达方式和停顿建议
  -> 人物/路人/旁白音色选角
  -> 作者复核朗读脚本
  -> 分段 TTS
  -> 音频后处理、缓存和拼接
  -> 文本位置与音频时间映射
  -> 播放、高亮和进度恢复
```

番茄未公开完整实现源码和客户端同步协议。本项目只采用由官方公开产品能力支持的架构模式。

## 3. 范围

### 3.1 纳入

- 书本管理新增独立“朗读”入口；
- 旁白声音与作品级朗读规则；
- 人物卡专属音色；
- 青年、中年、老人、儿童、中性等通用/路人音色池；
- 匿名说话人稳定绑定；
- 预设、上传参考录音和文字描述生成三种音色来源；
- 旁白/对白切分和正式人物识别；
- 情绪与表达方式建议；
- 低置信度人工复核；
- 本地规则分析和经用户授权的云端辅助分析两种隐私模式；
- 按章合成、增量重生成、缓存和失败恢复；
- 同一朗读脚本的多朗读版本与历史回溯；
- 句段级正文高亮和自动滚动；
- 播放进度保存；
- 后续全书批量生成和导出。

### 3.2 明确排除

- 逐字卡拉 OK 高亮；
- 实时多人语音聊天；
- 首版使用 8B MOSS-TTSD 作为本机默认模型；
- 未经授权的真人、名人或第三方声音克隆；
- 直接复制番茄或其他平台的私有音色和内部算法；
- 模型自动新增正式人物或直接修改小说正文；
- 默认把整章正文发送给云端模型；
- 首版跨句 rolling prompt、跨显示句段合成和逐字强制对齐；
- 第一版自动生成复杂情绪变体并静默替换已锁定音色。

## 4. 当前项目基础与必须保持的边界

**已核实事实**：

- [`NovelCharacter`](../../backend/models.py) 已有稳定 UUID、`novel_id`、角色类型、姓名、描述、`details`、生命周期和版本字段。
- [`DocumentRevision`](../../backend/models.py) 已保存不可变 Markdown、纯文本、内容哈希和来源。
- [`DocumentWorkingCopy`](../../backend/models.py) 已提供草稿版本和内容哈希。
- [`MediaAsset`](../../backend/models.py) 已预留小说媒体元数据、来源 revision、存储路径和内容哈希，但尚缺 MIME、字节数、资产类别、生命周期、保留策略和存储后端字段，实施时必须扩展，不能把现状误写为已满足朗读资产治理。
- 当前作品工作台导航为章节、大纲、角色、线索、设定，见 [`workbench-studio.ts`](../../frontend/src/workbench-studio.ts)。
- 当前正文控件实际仍是原生 `textarea`，见 [`workbench-v2.ts`](../../frontend/src/workbench-v2.ts)；规划中的 Monaco 尚未落地。
- 现有架构已经预留 `TTSAdapter`、`LocalMountedMediaStorage` 和 TTS 失败不影响正文的边界。

**项目决策**：

- 音色不能写入 `NovelCharacter.details`。当前人物保存逻辑会用性别、年龄、身份和性格重建 `details`，音色数据存在被覆盖风险；音色版本、参考录音、授权、缓存失效和历史引用也需要独立关系表。
- TTS 是 revision 绑定的可重建派生数据。失败、取消或清理不得修改 working copy、正式 revision、角色和故事账本。
- 浏览器只访问 PawApp API；浏览器不能直接访问模型 Runtime、模型目录或文件系统路径。
- 逻辑上保留 `TTSAdapter` 和 `VoiceDesignAdapter`；Nano 的物理运行方式由阶段 0 决定。即使采用本机 Sidecar，它也只是受控模型依赖，不是第二套业务 API、Agent Runtime 或权威任务系统。
- 现有 `ChapterGenerationJob`、`CreativeGenerationJob` 不作为 TTS 新建第三套调度器的理由。朗读使用共享持久任务领取、租约、重试和审计协议，领域表只保存朗读状态。

## 5. 产品信息架构

### 5.1 作品工作台导航

```text
章节
大纲
角色
线索
设定
朗读  <- 新增，位于“设定”下方
```

路由 section 新增稳定值 `reading`。新版工作台、兼容工作台、创作中心跳转、路由恢复、类型定义和测试必须同步扩展，不能只在一个导航数组里增加按钮。

### 5.2 “朗读”页面

```text
朗读
├── 总览
├── 旁白
├── 人物配音
├── 通用音色
├── 选角规则
├── 发音与停顿
└── 音频与缓存
```

#### 总览

显示：

- Nano Runtime 安装、健康和预热状态；
- VoiceGenerator 可用状态；
- 当前正文分析隐私模式及云端授权状态；
- 当前旁白；
- 正式人物音色覆盖率；
- 通用音色池覆盖率；
- 待复核脚本、已生成章节和失败任务；
- 模型、媒体和缓存磁盘占用；
- 测试朗读、初始化基础音色包、扫描缺失配置、批量生成和清理缓存入口；
- 不可删除源资产、可回收派生缓存和预计可释放空间分别统计。

#### 旁白

支持：

- 默认旁白音色和不可变版本；
- 内置、上传、文字生成三种来源；
- 语言、叙述风格及合成参数；
- 播放倍速和播放器音量；二者属于播放设置，不触发重新合成；
- 是否朗读章节标题、作者的话和分隔内容；
- 第一人称叙述使用旁白还是指定人物；
- 内心独白使用人物声还是旁白声；
- 可选分卷和章节旁白覆盖；覆盖必须落入 `narration_scope_overrides`，不能只存在于 UI；
- 试听、确认和版本历史。

#### 人物配音

集中显示每个正式人物：

- 专属音色、继承音色或未配置；
- 当前音色版本；
- 试听；
- 跳转人物卡声音设置；
- 受音色变更影响的章节和句段数量；
- 批量初始化或重生成入口。

#### 通用音色

管理路人、临时角色和缺少专属音色人物的音色池，详见第 6 节。

#### 选角规则

管理人物归因、匿名角色复用、同场景去重、备用声音、低置信度阈值、第一人称、内心独白、信件、电话、广播和群体声音规则，同时显示：

- `隐私优先`：本地规则无法确定时直接进入人工复核；
- `智能增强`：仅把不确定句段和最小上下文发送给当前受控聊天模型；必须单独确认作品级授权；
- 最近一次分析实际使用的供应商、模型和规则版本；
- 云端关闭后不会把已有云端判断冒充新的本地判断。

#### 发音与停顿

管理人名、地名、多音字、外语名、数字、年代、特殊称谓、朗读替换、句间停顿和不朗读规则。朗读替换只改变 `spoken_text`，不得修改正文。

#### 音频与缓存

按章节显示正文版本、脚本状态、生成状态、音色版本、时长、大小、失败句段、过期状态、重新生成、导出和删除缓存。

### 5.3 人物卡“声音”页签

人物卡增加：

- 是否使用专属声音；
- 音色来源；
- 可编辑音色描述；
- 试听文本；
- 多候选生成和试听；
- 上传参考录音；
- Nano 克隆测试；
- 确认锁定；
- 当前版本和历史版本；
- 默认语言与基础朗读参数；
- 继承的通用音色及转为专属音色入口。

### 5.4 章节编辑器

增加：

- `智能朗读`；
- 当前版本朗读状态；
- 朗读脚本复核面板；
- 固定或浮动播放器；
- 播放、暂停、倍速、上一句、下一句和拖动；
- 当前说话人和音色；
- 当前句段高亮和自动滚动；
- 点击句段跳转；
- 单句试听和重新生成；
- 正文版本过期提示。

播放器必须支持键盘操作、焦点可见、ARIA 标签和高对比度高亮。用户手动滚动后自动跟随暂停，并显示“返回当前朗读位置”；不得与用户争夺滚动位置。

正文 `content_hash` 与朗读版本不一致时，允许继续听旧版本，但只能在不可变朗读快照中高亮；不得把旧偏移映射到当前编辑稿。

## 6. 声音体系

### 6.1 声音类型

```text
旁白
正式人物专属声音
正式人物继承声音
匿名/路人声音
群体声音
未知备用声音
```

### 6.2 通用音色池最低分类

| 年龄感 | 男性 | 女性 | 首版建议槽位 |
| --- | --- | --- | ---: |
| 儿童 | 男童 | 女童 | 各 1–2 |
| 少年/少女 | 少年 | 少女 | 各 2 |
| 青年 | 青年男性 | 青年女性 | 各 3 |
| 中年 | 中年男性 | 中年女性 | 各 3 |
| 老年 | 老年男性 | 老年女性 | 各 2 |
| 中性/未知 | 中性声音 | — | 1–2 |
| 群体 | 众人/人群 | — | 1–2 |

按每类下限计算，完整基础池至少需要 24 个可区分槽位。官方当前附带的 6 个中文参考音色只能用于安装验证和应急降级，不能直接填满该矩阵。

**基础音色包闸门**：阶段 0 必须完成以下二选一，否则“自动通用选角”不得进入默认可见范围：

1. 使用 VoiceGenerator 为每个槽位生成至少 2 个候选，经人工试听、Nano 二次克隆和授权记录后锁定 24 个项目基础音色；
2. 准备不少于 24 个具有明确授权来源的内置参考音色，并通过同一套质量验收。

若只能得到较少声音，允许发布“有限音色预览”，但必须在 UI 显示缺失类别和撞声风险，不能宣称已完成完整通用音色池。

每个槽位是具体音色版本，例如“青年女性 A：清亮活泼”“青年女性 B：温柔内敛”。音色元数据至少包括：

- 性别；
- 年龄段；
- 语言；
- 音高和音色质感；
- 性格气质；
- 可选职业/场景标签；
- 适用与不适用标签；
- 是否启用；
- 优先级和版本。

标签只用于选角，不足以证明两个音色在听感上真正不同。首版由人工试听负责最终去重；可选声纹嵌入只作为相似度预警，不能代替作者确认，也不得在没有相应模型和基准时写成已实现能力。

### 6.3 匿名说话人

“店小二、老妇人、侍卫、陌生女子”等不强制建立正式人物卡，但系统必须创建可追踪的匿名说话人并稳定绑定声音。

默认规则：

- 自动复用范围默认为“场景或章节”，不因“老妇人、侍卫”等泛称相同就跨全书认定为同一人；
- 同一稳定匿名人物在其作用域内再次出现时复用原音色；
- 同一场景不同匿名人物尽量不用同一音色；
- 通用音色尽量避开同场景正式人物的音色；
- 重跑分析和合成不得随机换声音；
- 匿名人物跨多章反复出现时提示作者升级为正式人物卡；
- 升级必须由作者确认，并允许继承既有声音和历史别名。

系统必须提供匿名人物合并、拆分、重命名、调整作用域和转为正式人物的复核操作。跨章节复用必须来自明确别名/上下文证据或作者确认。

### 6.4 群体声音

第一版用一个群体代表音色并明确标记 `group`。高级版可将 2–3 个不同音色分别合成，加入轻微时间偏移后混合。群体混合是后处理能力，不把 Nano 描述为原生多人同时发声模型。

### 6.5 音色来源

#### 系统预设

用于安装验证、快速初始化旁白和有限降级。正式发布前必须核验预设文件、名称、授权和模型版本；不默认向用户展示名人模仿音色。官方预设与本项目锁定的 24 音色基础包必须分别标识，不能混为同一来源。

#### 上传参考录音

流程：

1. 用户选择文件并确认拥有授权；
2. 校验 MIME、扩展名、大小、时长和可解码性；
3. 检测过长静音、削波和明显噪声；
4. 保存原始私有资产；
5. 生成统一格式的参考音频；
6. 使用 Nano 生成固定测试句；
7. 作者试听；
8. 保存来源、授权和文件哈希；
9. 锁定音色版本。

#### 文字描述生成

流程：

```text
人物年龄/性别/身份/性格/小传
  -> 本地模板生成可编辑音色描述
  -> 作者确认描述
  -> VoiceGenerator 生成多个候选
  -> 作者试听选择
  -> 保存候选来源、描述、模型和种子
  -> Nano 克隆测试
  -> 作者锁定为不可变音色版本
```

默认由本地模板把年龄感、性别、音高、质感、语速倾向和性格标签组合成描述，不需要把人物小传发送给聊天模型。若以后提供 AI 润色，必须使用同一显式授权机制但单独说明“音色描述润色”用途，只发送作者勾选的最小字段；说话人分析授权不能自动扩张为该用途。最终描述必须由作者确认后才能交给本地 VoiceGenerator。

## 7. 自动选角

### 7.1 优先级

```text
1. 章节范围人工覆盖
2. 分卷范围人工覆盖
3. 作品级旁白与人工选角规则
4. 正式人物专属音色
5. 正式人物明确绑定的继承音色
6. 已存在匿名说话人绑定
7. 根据人物描述匹配通用音色池
8. 根据性别/年龄匹配备用池
9. 中性备用音色
10. 无法安全判断：待人工确认
```

### 7.2 选角流程

```text
当前句段
   │
   ├─ 旁白 -> 旁白音色
   │
   ├─ 正式人物
   │    ├─ 有专属音色 -> 专属音色
   │    └─ 无专属音色 -> 年龄/性别通用池
   │
   ├─ 已知匿名人物 -> 复用匿名绑定
   │
   ├─ 带描述的匿名人物
   │    ├─ 年轻女子 -> 青年女性池
   │    ├─ 老妇人 -> 老年女性池
   │    ├─ 中年男人 -> 中年男性池
   │    ├─ 小男孩 -> 男童池
   │    └─ 侍卫/医生/掌柜 -> 属性和职业标签匹配
   │
   ├─ 众人齐声 -> 群体规则
   │
   └─ 未知 -> 中性备用音色 + 待确认
```

### 7.3 稳定分配

通用音色选择使用确定性分配，输入至少包含：

```text
novel_id
+ anonymous_speaker_stable_key
+ generic_pool_version
+ scene_scope（仅用于同场景排除）
```

同一稳定键在同一通用池版本下得到相同 slot。音色池升级不能改变任何历史 Edition；从同一已审批脚本创建新 Edition 时，默认沿用原 settings snapshot/pool version，只有作者显式选择“使用新音色池重新选角”才解析新 pool，并在创建前展示受影响人物和句段。

`scene_scope` 不是自由字符串。分析器先根据章节结构、显式分隔符和段落边界生成 `narration_scenes`；无法确定场景时退回章节范围。匿名稳定键由标准化描述、作用域、首次出现局部锚点和显式别名共同生成，并保留生成算法版本。哈希碰撞、泛称冲突或跨章疑似复现必须进入人工合并/拆分流程，不能静默合并。

### 7.4 可配置规则

- 同场景是否禁止重复音色；
- 未配置正式人物是否自动继承；
- 匿名人物复用范围：句段、场景、章节、全书；
- 第一人称叙述和内心独白规则；
- 信件、短信、电话、广播和回忆的表达方式；
- 众人齐声采用代表声还是群体混合；
- 低置信度阈值；
- 是否允许自动推断年龄、性别和职业；
- 是否在匿名人物多次出现时提示建卡。

### 7.5 前置数据依赖

自动选角开工前必须先实现或明确降级：

- `character_aliases`：人物别名、规范化值、冲突状态和来源；
- `narration_scenes`：脚本内场景边界和结构来源；
- 匿名人物合并、拆分和作用域调整；
- 声音解析器的章节 > 分卷 > 作品优先级测试。

缺少别名或场景数据时允许降低自动识别率并要求人工复核，但不能伪造“当前场景人物”或跨章稳定身份。

## 8. 正文分析与朗读脚本

### 8.1 保存屏障

用户点击智能朗读时必须：

1. 等待当前自动保存完成；
2. 校验 `draft_version`；
3. 读取并确认 `content_hash`；
4. 查找该文档内容哈希完全相同的既有 revision，存在则直接复用；
5. 不存在时幂等创建隐藏的 `tts_snapshot` revision；
6. `tts_snapshot` 不移动 working copy 的 `base_revision_id`，不增加 `draft_version`，默认不出现在用户手工检查点历史中；
7. 对 `(document_id, content_hash, snapshot_purpose)` 建立唯一约束或等价幂等保证；
8. 将朗读脚本绑定精确 `revision_id` 和 `content_hash`；
9. 任何后续编辑都不能改变该脚本的来源文本。

不得直接复用当前 `create_checkpoint()` 的行为：它会无条件创建 `manual_checkpoint`、推进 revision number 并更新 working copy 基线，连续点击朗读会污染版本历史。

### 8.2 Markdown 与句段切分

解析器需要识别：

- 标题和正文；
- 段落与标点；
- `“”`、`「」`、`『』` 和英文引号；
- 冒号、破折号和嵌套引号；
- 对话提示语；
- 内心独白；
- 短信、信件、广播和电话；
- 场景分隔符与作者注释；
- 不朗读标记。

每个句段同时保存：

- Markdown 源位置；
- 前端使用的 UTF-16 起止偏移；
- 原文；
- 实际朗读文本 `spoken_text`；
- 局部内容哈希；
- 前后必要上下文。

章节标题、自动插入停顿等没有直接正文字符范围的合成项必须使用独立 `segment_kind`，其源偏移允许为空；不得伪造正文范围。

前后端必须冻结 UTF-16 偏移契约并覆盖 emoji、组合字符和特殊标点测试，避免浏览器选择范围与 Python code point 计数不一致。

### 8.3 规则优先

确定性规则先处理明确情形：

```text
林晚说道：“你终于来了。”       -> 林晚
“你终于来了。”林晚轻声说道。   -> 林晚
沈川皱眉。“我没有骗你。”       -> 沈川
“别动！”一个年轻女人喊道。     -> 匿名青年女性
```

规则至少使用：

- 人物姓名和别名；
- 说、问、喊、答、低语、暗道等提示动词；
- 前后提示语；
- 同段连续说话；
- 当前场景人物；
- 上一说话人和轮次；
- 第一人称与内心独白设置。

### 8.4 模型补充判断

作品级正文分析模式只能为：

```text
local_rules_only
  -> 规则无法确定时标记 unknown/低置信度并进入人工复核

cloud_assisted
  -> 用户明确授权后，仅把不确定句段、最小前后文和有限候选人物发送给受控聊天模型
```

`cloud_assisted` 输入包含当前句、必要前后文、候选人物与别名、有限角色属性、当前场景和前一说话人。禁止默认发送整章、完整人物库、参考录音或未参与判断的设定。授权记录必须包含作品、用途、模式版本、时间和撤销状态。

模型输出必须通过严格 JSON Schema，并且 `speaker_kind` 只能为：

```text
narrator
character
anonymous
group
unknown
```

当 `speaker_kind=character` 时，`character_id` 必须属于本次输入的允许集合。模型不能新增或修改正式人物。非法 ID、缺失证据或结构不合格的输出必须转为 `unknown`，不能猜测后写入权威数据。

长章节按场景/窗口处理，只对不确定句段调用模型，并在窗口边界保留重叠上下文。相邻窗口结果冲突时转入复核。每次调用保存 requested/actual provider、model、提示模板版本、输入哈希和结果哈希；当前项目实际模型校验规则继续生效，模型身份不匹配时结果作废。

### 8.5 情绪与表达方式

情绪和表达方式分开保存：

```text
emotion: neutral | happy | sad | angry | fearful | tense
delivery: normal | whisper | shout | inner_monologue
```

第一版只把它们用于脚本标记、人工复核、基础停顿和有限生成参数。不同情绪参考音频必须由作者试听确认；不自动为每个情绪重新创造人物音色。

### 8.6 置信度和人工优先

每个句段保存说话人置信度、情绪置信度、判断证据、规则/模型来源和人工覆盖状态。

模型自报的数值不是经过校准的真实概率。最终置信等级由可解释规则信号、候选冲突、模型一致性和固定标注集校准共同决定；在校准完成前只使用 `high | medium | low | unknown` 等级，不向用户展示伪精确百分比。

- 高置信度：默认通过；
- 中置信度：可见但不强制阻塞；
- 低置信度：必须复核；
- `unknown`：不得静默生成正式成品；
- 作者修改后设为 durable override；同一脚本版本内后续自动分析不得覆盖，除非作者显式重置；
- 新正文版本只在“原文局部哈希、唯一前后锚点和说话人目标”全部匹配时继承人工覆盖；歧义、改写或多处重复文本必须重新复核。

## 9. 朗读脚本复核

```text
[旁白][平静] 夜色笼罩着长安城。
[林晚][冷淡] “你终于来了。”
[沈川][压抑] “我一直都在。”
[未知角色][低置信度] “你们两个都被骗了。”
```

作者可以：

- 修改正式人物；
- 设为旁白、匿名、群体或未知；
- 新建匿名说话人；
- 把匿名说话人升级为正式人物候选；
- 修改情绪和表达方式；
- 调整场景边界和匿名人物作用域；
- 修改 `spoken_text` 而不修改正文；
- 调整前后停顿；
- 合并或拆分句段；
- 单句试听；
- 只重分析当前句；
- 批量修改同一匿名说话人；
- 审批整章脚本。

脚本未审批前不进入正式朗读版本合成。允许快速试听单句，但试听资产必须标为临时派生数据。

审批会冻结一个不可变 `narration_script_version`。审批后的修改不能原地覆盖，必须创建新的脚本版本；旧朗读版本继续引用旧脚本版本。这样才能复现历史配音并准确计算失效范围。

## 10. 音频生成、时间轴和播放

### 10.1 合成单元

- 首版一个显示句段对应一个独立最终 `segment_render`；
- 对话通常以一个完整引号段为显示句段，旁白按句子或短段落切分；
- 不跨显示句段合并模型请求，不依赖模型返回内部时间戳；
- 超过 Nano 长度预算的单个显示句段可在 Runtime 内拆成多个 `render_part`，合成后拼为一个句段资产，前端仍只做句段级高亮；
- 首版禁用跨句 rolling prompt。每个句段只依赖自身文本、锁定音色和冻结参数；
- 只有独立基准证明质量收益大于缓存连锁失效和重试复杂度后，后续版本才能增加上下文模式。

这一约束是句段同步、局部重生成和崩溃恢复的共同基础，不能为了少量吞吐优化提前取消。

### 10.2 缓存键

句段缓存键至少包含：

```text
canonical_spoken_text_hash
+ pronunciation_profile_fingerprint
+ voice_profile_version_fingerprint
+ reference_audio_hash
+ tts_model_revision
+ tokenizer_revision
+ normalizer_version
+ language
+ synthesis_style_and_parameters
+ deterministic_seed
+ postprocess_version_and_master_format
```

指纹由版本化 canonical JSON 计算，禁止依赖对象键顺序或浮点字符串偶然格式。`spoken_text` 必须是完成发音词典、数字和停顿前文本规范化后的最终模型输入；发音表变化即使最终文本偶然相同，也由 `pronunciation_profile_fingerprint` 明确记录来源。

播放倍速和播放器音量不进入 render 缓存键，因为它们由播放层实时处理。会改变发声结果的风格、情绪变体或速度参数只有在 Nano/VoiceGenerator 阶段 0 明确支持并通过验收后，才进入合成参数。

朗读版本 Manifest 指纹由有序句段 render 哈希、句间停顿、播放格式和 Manifest schema 版本共同决定。首版不存在“整章播放文件缓存键”；整章文件只在显式导出时生成。

### 10.3 生成顺序

1. 审批并冻结脚本版本；
2. 冻结朗读设置快照、发音表版本、模型 fingerprint 和所有音色版本；
3. 创建幂等 `narration_edition`；
4. 为每个句段解析最终音色版本并保存解析证据；
5. 计算句段 render fingerprint；
6. 复用命中缓存，并立即把已命中句段写入 Edition Manifest；
7. 缺失句段进入共享持久任务队列；
8. 按“交互试听 > 当前章节开头 > 当前章节剩余 > 批量 > 导出”排序；
9. M4 初始默认单并发运行 Nano；
10. 校验输出可解码、非空、非异常长度；
11. 检查严重静音、削波、峰值、响度和时长异常；
12. 保存无损/可重建 master 和浏览器播放资产；
13. 写入真实句段时长、停顿和 render 状态；
14. 每完成一个可连续播放的前缀就更新 Manifest revision；
15. 前缀达到最小播放门槛时将 Edition 标记 `partial_ready`；
16. 所有必需句段完成并校验后标记 Edition `ready`；
17. 仅在用户导出时生成章节或全书连续文件。

最小播放门槛的初始候选为“连续至少 3 个句段且累计至少 8 秒，或短章节已经全部完成”；最终值由阶段 0 接缝和生成速度基准冻结，并作为 `initial_buffer_policy_version` 写入 Edition/Manifest，不能由前端临时猜测。

### 10.4 长篇一致性

采用固定参考音频、不可变音色版本、固定模型 revision、稳定种子和稳定采样参数。核心首版明确使用 `independent_segment` 上下文模式。

以后若增加 rolling prompt，必须创建新的上下文模式和缓存 schema，把前序音频/文本尾部哈希加入指纹，并定义从修改点向后的连锁失效；不得在同一缓存命名空间内静默开启。

### 10.5 播放清单

```json
{
  "schema_version": 1,
  "edition_id": "edition-123",
  "revision_id": "revision-123",
  "content_hash": "sha256...",
  "status": "partial_ready",
  "ready_prefix_count": 3,
  "duration_ms": null,
  "segments": [
    {
      "segment_id": "segment-1",
      "ordinal": 1,
      "source_start_utf16": 0,
      "source_end_utf16": 9,
      "render_status": "ready",
      "asset_url": "/media-assets/asset-1/content",
      "duration_ms": 2800,
      "gap_after_ms": 260,
      "speaker_kind": "narrator",
      "character_id": null
    },
    {
      "segment_id": "segment-2",
      "ordinal": 2,
      "source_start_utf16": 9,
      "source_end_utf16": 20,
      "render_status": "ready",
      "asset_url": "/media-assets/asset-2/content",
      "duration_ms": 3100,
      "gap_after_ms": 220,
      "speaker_kind": "character",
      "character_id": "character-1"
    },
    {
      "segment_id": "segment-3",
      "ordinal": 3,
      "source_start_utf16": 20,
      "source_end_utf16": 31,
      "render_status": "ready",
      "asset_url": "/media-assets/asset-3/content",
      "duration_ms": 2600,
      "gap_after_ms": 0,
      "speaker_kind": "character",
      "character_id": "character-2"
    }
  ]
}
```

Manifest 是分段播放清单，不要求先存在整章音频。只允许从第一个句段开始形成连续 `ready` 前缀；中间缺失的句段不能被播放器静默跳过。

前端播放器通过统一 `SegmentPlaybackQueue` 预取后续 3–5 个句段。优先验证 Web Audio 调度以减少分段间隙；若宿主环境不兼容，则回退双 `<audio>` 预加载，但必须记录可听间隙并进入阶段 0/5 验收。当前播放会话保持同一 Manifest revision，不在播放中途无感切换到另一整章文件。

### 10.6 编辑器跟随

播放器以当前 `segment_id` 为句段级同步权威；完整 Edition 准备后可根据累计时长支持全章拖动。播放倍速由播放层应用，不能修改原始句段时间数据。

当前 `textarea` 首版采用同一编辑区域内的只读朗读覆盖层：每个句段渲染为可点击 span，播放时高亮；返回编辑前暂停或退出朗读视图。Monaco 落地后改用公共 decorations/range API，不访问内部实现。

### 10.7 正文变化

正文 `content_hash` 与 manifest 不一致时：

- 立即停止把旧时间轴映射到新正文；
- 将对应脚本标为 `stale`，旧 Edition 保持不可变历史状态；
- 允许在不可变旧版本朗读视图中继续播放；
- 提供按当前正文重新分析；
- 相同文本、音色和模型的句段仍可命中缓存。

## 11. 数据模型

### 11.1 关系总览

```text
DocumentRevision
  └─ NarrationScript
       └─ NarrationScriptVersion
            ├─ NarrationScene
            └─ NarrationSegment
                 └─ NarrationEditionSegment ──► SegmentRender ──► MediaAsset

NarrationScriptVersion
  + NarrationSettingsSnapshot
  + VoiceProfileVersions
  + TTS/Normalizer fingerprints
  └─ NarrationEdition ──► NarrationManifest

BackgroundJob ──► ModelRunRecord
```

权威层级：正文 revision 是文本权威；已审批脚本版本是说话人/朗读文本权威；Edition 是一次配音制作配置权威；render 和媒体均为可校验派生物。

### 11.2 `media_assets` 扩展

在现有字段上增加：

- 本地 `owner_id`/profile scope，并把 `novel_id` 调整为可空；个人复用音色资产使用 owner scope，作品音频同时校验 novel scope；
- `asset_class`: `source | voice_reference | preview | segment_master | segment_playback | export`；
- `mime_type`、`byte_size`、`duration_ms`、`sample_rate`、`channels`；
- `storage_backend`、`state`、`retention_policy`；
- `verified_at`、`checksum_algorithm`、`last_accessed_at`；
- 可选 `expires_at`、`deleted_at` 和结构化校验结果。

迁移必须为现有资产回填固定本地 owner，并用 CHECK/服务层约束保证资产至少有 owner；任何带 `novel_id` 的访问还要验证小说属于当前 owner。不能为了实现跨书声音库继续强迫私人参考音频伪装成某本小说的资产。

保留策略：上传原件、标准化参考音频和锁定音色不可被普通“清缓存”删除；试听、segment master、播放副本和导出属于可重建派生物，按引用可达性和配额清理。物理删除前必须检查人物绑定、脚本版本、Edition 和历史 render 引用。

### 11.3 `voice_profiles` 与 `voice_profile_versions`

`voice_profiles` 是稳定音色身份，保存 owner/novel scope、名称、当前版本、状态、CAS 版本和归档时间。

`voice_profile_versions` 是不可变版本，至少保存：

- `source_type`: `preset | uploaded | generated`；
- provider/model/revision、预设键、参考和试听资产；
- 文字描述、试听文本、语言、标签和规范化参数；
- 随机种子、fingerprint、来源和授权确认；
- 创建时间、质量审核状态和锁定人/时间。

被脚本、Edition 或 render 引用的版本不可原地修改。

### 11.4 `character_aliases` 与 `character_voice_bindings`

`character_aliases` 保存 `novel_id`、`character_id`、原别名、规范化别名、来源、冲突状态和生命周期。相同规范化别名指向多个活跃人物时必须标记冲突，不能由规则静默选择。

`character_voice_bindings` 保存：

- `character_id` 唯一；
- profile 和可选锁定 version；
- 专属/继承策略、默认语言及已验证的有限合成参数；
- CAS 版本和时间戳。

角色归档不级联删除历史音色或朗读。

### 11.5 `novel_narration_settings`、版本与范围覆盖

`novel_narration_settings` 指向当前可编辑配置；每次用于正式合成时冻结 `narration_settings_snapshot`，保存：

- 默认旁白 profile/version；
- 标题、作者注、第一人称和内心独白规则；
- 正文分析模式与云端授权引用；
- 默认语言、停顿、播放格式和低置信度策略；
- 默认通用池、选角规则和发音表 fingerprint；
- schema/version/fingerprint。

`narration_scope_overrides` 使用 `scope_kind = volume | chapter` 与 `scope_id`，保存旁白和有限规则覆盖。解析顺序固定为章节 > 分卷 > 作品，并用数据库约束保证 scope 属于同一小说。

`narration_cloud_consents` 保存 `novel_id`、用途、告知文本版本、允许的数据范围、可选 provider/model scope、确认时间和撤销时间。授权记录不可被普通设置覆盖；撤销后所有新 job 必须在执行前再次校验，排队时已授权不代表真正调用时仍获授权。

播放倍速和播放器音量属于个人播放偏好，不写入合成设置快照。

### 11.6 `generic_voice_pools` 与 `generic_voice_slots`

Pool 保存作品、版本、年龄/性别/用途分类和状态；slot 保存排序、不可变音色版本、标签、启用状态和优先级。历史脚本/Edition 引用具体 slot 与 voice version，不能只保存“青年女性”字符串。

### 11.7 `voice_casting_rules` 与 `narration_scenes`

`voice_casting_rules` 保存作品范围、优先级、条件 schema、目标 pool/slot/动作、同场景去重、匿名复用、回退策略、来源、版本和归档状态。

`narration_scenes` 属于脚本版本，保存场景序号、源范围、边界来源、场景局部哈希和可选人工标题。它是同场景去重和匿名作用域的明确数据来源。

### 11.8 `anonymous_speakers` 与绑定

- 作品、稳定键、稳定键算法版本、显示名称和描述；
- 默认作用域 `scene | chapter | novel` 及 scope ID；
- 首次/最近来源 revision、脚本版本和句段；
- 推断年龄、性别、职业、证据和置信等级；
- slot、voice version、人工覆盖和生命周期；
- 可选 `promoted_character_id`、合并来源和拆分记录。

### 11.9 `pronunciation_profiles` 与 `pronunciation_entries`

正式合成引用不可变 `pronunciation_profile` fingerprint。Entry 保存原文本、最终朗读替换或经验证的音素表示、语言、作用域、优先级、大小写策略、来源和版本。

匹配顺序固定为章节 > 分卷 > 作品、人工条目 > 系统规范化、长匹配 > 短匹配；同优先级冲突必须提示，首版不开放任意正则替换。转换只生成 `spoken_text`，正文和原始 segment 文本保持不变。

Nano 不支持的标记语法不得直接送入模型；阶段 0 先验证中文多音字、数字和中英混读的可用控制方式。

### 11.10 `narration_scripts` 与 `narration_script_versions`

`narration_scripts` 是 document/revision 下的稳定分析身份，绑定精确 `revision_id` 和 `content_hash`。

`narration_script_versions` 保存分析器、规则、分析/选角设置 fingerprint、提示模板、requested/actual model fingerprint、状态、统计、审批信息、父版本和唯一幂等键。草稿通过 CAS 修改；一旦审批即不可变。正文变化只把旧脚本标为 `stale`，不改写旧版本。

### 11.11 `narration_segments`

- 脚本版本、场景、稳定序号和 `segment_kind`；
- 可空 Markdown/UTF-16 起止位置；
- 原文、最终 `spoken_text`、局部哈希和前后锚点；
- `speaker_kind`、character/anonymous ID；
- 情绪、表达方式、前后停顿；
- 规则/模型来源、证据和置信等级；
- 候选及最终 casting target（character binding、anonymous binding、slot 或 profile 身份）；脚本不冻结最终 voice version；
- `manual_override`、继承来源和版本。

### 11.12 `narration_editions` 与 `narration_edition_segments`

`narration_editions` 是一次可复现制作版本，绑定：

- 已审批 script version；
- settings snapshot、pronunciation profile；
- TTS/Tokenizer/Normalizer/postprocess fingerprints；
- 上下文模式，首版固定 `independent_segment`；
- 初始缓冲策略版本；
- 状态、当前 Manifest revision、创建人和时间；
- 由上述输入计算的唯一 edition fingerprint。

`narration_edition_segments` 保存 Edition 内句段顺序、按当次设置解析出的最终 slot/profile/voice version、解析证据、render fingerprint、render 状态、gap 和失败信息。同一脚本版本可拥有多个 Edition。

### 11.13 `narration_segment_renders`

- 唯一 render fingerprint；
- canonical 输入、voice/reference、模型和后处理 fingerprints；
- master/playback `media_asset_id`、时长和音频校验信息；
- 状态、来源 job 和时间戳。

Render 不属于某一个脚本；满足相同隐私 scope 和完整 fingerprint 时可复用。首版缓存限定在同一本地 owner/workspace，避免跨用户复用私人正文和私人音色。

### 11.14 `narration_manifests` 与播放进度

Manifest 绑定 Edition，保存 schema version、Manifest revision、连续 ready 前缀、有序 segment/render 哈希、总时长、状态和结构化 JSON。更新使用 CAS；旧 Manifest revision 在正在播放的会话结束前保持可读取。

`narration_playback_progress` 保存本地 owner/profile、Edition、Manifest revision、最后 segment、句内偏移、倍速和更新时间。正文或 Edition 更新后保留历史进度，但不自动迁移到不同内容哈希。

### 11.15 `background_jobs` 与 `model_run_records`

不再新增独立 `narration_jobs` 调度体系。共享 `background_jobs` 至少保存：

- `job_kind`: `narration.analyze | narration.voice_preview | narration.segment_render | narration.export` 等命名空间；
- 本地 `owner_id`、可选 `novel_id`、`scope_kind`、`scope_id`、可选 `source_revision_id`；
- 输入哈希、唯一幂等键、优先级和资源类别；
- `queued | running | succeeded | failed | cancelled | dead_letter`；
- `locked_by`、`lease_until`、attempts、`next_retry_at`；
- 进度、错误分类、取消请求和时间戳。

`model_run_records` 逐次记录 requested/actual provider、model/revision、参数 fingerprint、输入/输出哈希、耗时、供应商请求 ID 和失败信息。朗读 Edition 的 `partial_ready/ready` 是领域状态，不是 job 状态。

领取必须使用 PostgreSQL 原子锁/租约；前端 PawTask/SSE 只展示进度，不是持久权威。共享执行器可被后续 Embedding、情报派生和媒体任务复用；现有专用生成 job 的迁移另行评审，不在朗读阶段偷偷重写。

优先级调度必须带等待时间老化和资源类别配额，避免持续单句试听永久饿死全书任务。Nano、VoiceGenerator、CPU 转码分别声明资源类别；同一模型重任务默认单并发，轻量校验/转码可在阶段 0 基准后独立限流。

取消是协作式请求：执行器在调用前、分段间和写入前检查 `cancel_requested_at`。若底层模型不能立即中断，允许本次计算结束，但取消后的结果不得发布到 Edition；只有通过完整 fingerprint 校验且仍有其他有效引用时才可作为缓存保留。

## 12. 状态机

### 12.1 音色

```text
draft
  -> generating
  -> preview_ready
  -> locked
  -> retired

generating -> failed -> generating
```

### 12.2 朗读脚本

```text
analyzing
  -> review_required
  -> approved

正文更新 -> stale
分析失败 -> failed
approved 后修改 -> 新建 script version -> review_required
```

脚本状态只表达分析与审批，不表达音频合成。

### 12.3 朗读版本 Edition

```text
queued
  -> rendering
  -> partial_ready
  -> ready

rendering/partial_ready -> failed -> rendering（重试）
ready -> superseded（新 Edition 被设为当前）
```

旧 Edition 不因正文或音色更新被改写；它只是不再是当前版本。

### 12.4 后台任务

```text
queued
  -> running
  -> succeeded

running -> failed -> queued（显式/策略重试）
running -> cancelled
进程失联 -> lease 过期 -> 重新领取
达到上限 -> dead_letter -> 人工重试
```

## 13. API 草案

所有修改接口使用 `expected_version` 或幂等键；任务创建支持 `Idempotency-Key`；进度优先使用 SSE，断线后可用 GET 恢复。

### 13.1 设置和总览

```text
GET  /novels/{novel_id}/narration-overview
GET  /novels/{novel_id}/narration-settings
PUT  /novels/{novel_id}/narration-settings
GET  /novels/{novel_id}/narration-scope-overrides
PUT  /novels/{novel_id}/narration-scope-overrides/{scope_kind}/{scope_id}
POST /novels/{novel_id}/narration-cloud-consents
DELETE /novels/{novel_id}/narration-cloud-consents/current
```

### 13.2 音色

```text
GET    /voice-profiles
POST   /voice-profiles
GET    /voice-profiles/{voice_profile_id}
PUT    /voice-profiles/{voice_profile_id}
DELETE /voice-profiles/{voice_profile_id}
POST   /voice-profiles/{voice_profile_id}/previews
POST   /voice-profiles/{voice_profile_id}/lock
PUT    /novels/{novel_id}/characters/{character_id}/voice-binding
```

### 13.3 通用音色和选角

```text
GET /novels/{novel_id}/generic-voice-pools
PUT /novels/{novel_id}/generic-voice-pools
GET /novels/{novel_id}/casting-rules
PUT /novels/{novel_id}/casting-rules
GET /novels/{novel_id}/anonymous-speakers
PUT /novels/{novel_id}/anonymous-speakers/{speaker_id}
POST /novels/{novel_id}/anonymous-speakers/merge
POST /novels/{novel_id}/anonymous-speakers/{speaker_id}/split
POST /novels/{novel_id}/anonymous-speakers/{speaker_id}/promote
```

### 13.4 脚本

```text
POST  /documents/{document_id}/narration-scripts/analyze
GET   /narration-scripts/{script_id}
GET   /narration-script-versions/{version_id}
PATCH /narration-script-versions/{version_id}/segments/{segment_id}
POST  /narration-script-versions/{version_id}/approve
POST  /narration-script-versions/{version_id}/reanalyze-segments
```

### 13.5 生成和播放

```text
POST /narration-script-versions/{version_id}/editions
GET  /narration-editions/{edition_id}
GET  /narration-editions/{edition_id}/manifest
POST /narration-editions/{edition_id}/retry-failed-segments
POST /narration-editions/{edition_id}/export
GET  /background-jobs/{job_id}
GET  /background-jobs/{job_id}/events
POST /background-jobs/{job_id}/retry
POST /background-jobs/{job_id}/cancel
GET  /media-assets/{asset_id}/content
PUT  /narration-editions/{edition_id}/playback-progress
```

云端授权接口不得与普通设置 PUT 混在一起静默开启。媒体读取支持 Range、ETag 和内容类型校验；API 返回受控媒体 URL，不返回服务器文件路径或供应商临时 URL。Manifest 使用 `ETag`/revision 支持增量轮询；SSE 只用于加快状态更新，不能成为恢复权威。

## 14. 运行拓扑与资源

### 14.1 服务边界

```text
浏览器
  -> PawApp API
       ├─ NarrationService / ScriptAnalyzer / VoiceCastingService
       ├─ BackgroundJobRunner
       ├─ MediaStorage / PostgreSQL
       ├─ TTSAdapter ──► NanoExecutionBackend
       └─ VoiceDesignAdapter ──► VoiceGeneratorExecutionBackend（按需）
```

浏览器永远只访问 PawApp API。`NanoExecutionBackend` 是逻辑执行边界，不预先等同于第二个 HTTP 服务。

**项目决策**：不创建第二套业务 Web API、Agent Runtime 或任务账本；允许经阶段 0 选择受后台管理的本地模型进程。若使用 Sidecar，它只暴露窄模型契约，不拥有小说、人物、脚本、任务或媒体业务状态。

### 14.2 Nano 部署闸门

官方已提供无 PyTorch 的独立 ONNX CPU 路径、浏览器 ONNX 路径和本地服务示例。阶段 0 对同一基准集测试：

1. PawApp 后端进程内 ONNX CPU：最少拓扑，验证依赖冲突、事件循环阻塞和崩溃影响；
2. 后端受管 macOS 原生子进程：验证 IPC/loopback、自动拉起、日志和资源释放；
3. Linux ARM64 Compose Sidecar ONNX：验证部署一致性、挂载和容器开销；
4. 浏览器 ONNX：只作为未来低延迟试听候选，验证模型下载、缓存、内存、页面关闭和宿主 CSP；
5. 各路径统一测冷启动、预热首包、RTF、峰值内存、连续 30 分钟稳定性、取消和重启恢复。

首选顺序：进程内 ONNX 达标则采用；依赖/故障隔离不达标则采用受管本机子进程；容器部署环境再选 Sidecar。浏览器 ONNX 不作为正式批量生成默认路径，因为页面生命周期不能承担持久任务、媒体落盘和崩溃恢复。

上层 `TTSAdapter` 契约保持不变，至少提供 capabilities/health/warmup/synthesize/cancel/model-fingerprint。物理部署切换不得改变 Edition fingerprint 的语义。

若使用 loopback HTTP：只监听 `127.0.0.1` 或容器私网，使用随机启动令牌、请求大小限制、版本握手和超时；浏览器不可访问。若使用 IPC，应同样校验协议版本和路径白名单。

### 14.3 VoiceGenerator

优先验证 macOS MPS，其次验证可接受的 CPU/其他本地路径。它只在创建音色或阶段 0 制作基础音色包时加载，完成后释放；Nano 和 VoiceGenerator 默认不同时常驻，并由共享 `gpu_heavy` 资源锁串行化。

VoiceGenerator UI 可以后置，但完整通用音色池的“离线制作与锁定”必须在阶段 0 完成。若 M4 运行不达标，则使用有授权的预制基础音色包；若二者都没有，核心多角色范围降级而不是继续假定预设足够。

### 14.4 持久存储

Compose/本机增加：

```text
moss-models    模型权重、锁定 revision 和经过校验的 manifest
novel-media    参考录音、试听、句段 master、播放副本和导出音频
```

模型文件不写入 Git。模型版本、revision、文件清单和哈希保存在部署配置/数据库中。下载必须支持临时文件、断点/重试、哈希校验和原子改名，不能把半下载文件标记为可用。

### 14.5 音频格式和容量

- Nano 原生输出按官方能力为 48 kHz 双声道；阶段 0 验证是否保留双声道或在后处理规范化为单声道；
- 参考音频：保留原始私有资产和标准化无损版本；
- 句段 master：优先 FLAC 或经验证的无损格式，便于重建播放副本和导出；
- 句段播放副本：经浏览器兼容验证后选择 Opus/AAC；
- 章节/全书连续文件：只在显式导出时生成，避免每次局部修改重复转码；
- 临时 WAV 在 master 和播放副本均校验成功后删除；
- 官方 Nano ONNX 单个 TTS shared-data 文件约 441 MB，完整 Nano、Audio Tokenizer 和运行依赖以锁定 revision 实测为准；VoiceGenerator 当前权重约 4.23 GB；
- 一本 200 章小说的压缩音频预计为数 GB，必须有配额、过期缓存清理和磁盘不足提示。

阶段 0 必须固定 ffmpeg 或等价转码器版本并验证可用性；缺少转码器时不得生成只有数据库记录、没有可播放文件的半成品。

参考录音、锁定音色和无法重新取得的用户资产必须备份；可重建章节音频可按策略排除普通备份。

## 15. 安全、隐私和授权

- 上传录音前要求用户确认拥有授权；
- 保存来源类型、授权确认时间和可选说明；
- 自定义音色、参考录音和 TTS 合成始终默认只在本地处理；
- 正文分析默认 `local_rules_only`；只有作品级 `cloud_assisted` 明确授权后，才发送不确定句段和最小上下文；
- 撤销云端授权只阻止未来调用，不伪造删除供应商侧已经处理的数据；界面必须说明供应商数据政策由其条款决定；
- 云端分析请求不包含参考录音、音频资产、完整人物库或整章正文；
- 不在日志、错误跟踪或遥测中记录完整正文、参考录音或音频内容；
- `model_run_records` 保存哈希和审计元数据，不保存可还原正文的提示全文；
- 校验 MIME、大小、时长、解码、路径和文件名；
- 禁止目录穿越和任意文件读取；
- 浏览器不接触模型目录、服务端路径和第三方密钥；
- 本机模型进程只接受后台签发的请求，限制文件根目录、请求大小、并发和超时；
- 被人物、脚本或历史 render 引用的音色只能归档；
- 物理删除前生成引用影响预览；
- 提供彻底删除私人音色和源录音的显式操作；
- “仅删除上传原件”和“彻底删除该私人音色”必须是两个不同操作；彻底删除前展示受影响人物、脚本、Edition 和历史音频，确认后删除原件、标准化参考、试听、使用该音色的句段/导出音频并留下不可还原的 tombstone 审计，普通清缓存不能执行该操作；
- 不默认展示或宣传名人模仿声音；
- Apache 2.0 模型许可证不替代声音权利、人格权和使用场景审查。

## 16. 完整主流程

### 16.1 首次配置

1. 用户进入书本“朗读”；
2. 检查模型安装、哈希、执行后端和磁盘；
3. 下载缺失模型并显示可恢复进度；
4. 预热 Nano；
5. 选择 `local_rules_only` 或明确授权 `cloud_assisted`；
6. 配置默认旁白；
7. 校验并初始化 24 槽位基础音色包；
8. 配置第一人称、内心独白、标题和备用规则；
9. 扫描正式人物音色覆盖率和别名冲突；
10. 给主要人物设置专属音色；
11. 建立发音词典；
12. 用固定测试文本试听并锁定声音；
13. 冻结首个 narration settings snapshot。

### 16.2 生成章节朗读

1. 作者点击章节“智能朗读”；
2. 前端完成保存屏障；
3. 后端复用相同哈希 revision 或幂等创建隐藏 `tts_snapshot`；
4. 创建幂等分析任务；
5. 解析 Markdown 并保留偏移；
6. 生成场景边界并加载人物别名；
7. 按规则识别旁白和明确说话人；
8. 仅在授权的智能增强模式下，对不确定句段调用受控模型；
9. 建立/匹配匿名说话人，冲突项进入复核；
10. 预测有限情绪和表达方式；
11. 应用章节、分卷、作品、人物和通用音色优先级；
12. 校验所有 character ID 和 scope 归属；
13. 生成带证据和置信等级的脚本草稿；
14. 作者复核低置信度、unknown、别名冲突和匿名人物；
15. 作者审批并冻结脚本版本；
16. 冻结设置/发音/模型/音色并创建 Edition；
17. 计算所有句段 render fingerprint；
18. 复用命中 render 并发布初始 Manifest；
19. 对缺失句段建立共享持久任务；
20. 优先合成章节连续开头；
21. 校验、标准化并保存 master/播放资产；
22. 每个句段完成后更新 Manifest；
23. 达到连续前缀门槛后标记 `partial_ready`；
24. 前端按 Segment Manifest 预加载和播放；
25. 校验当前正文 hash 后按 segment ID 高亮；
26. 保存播放进度；
27. 失败句段可单独重试；
28. 所有句段完成后 Edition 标记 `ready`。

### 16.3 修改和失效

- 修改正文：新 revision 的脚本重新分析；满足唯一锚点条件的人工覆盖可迁移，相同句段仍可复用 render；旧脚本标记 `stale`，旧 Edition 保留。
- 修改某一句说话人或 `spoken_text`：创建新脚本版本，审批后创建新 Edition；只缺失必要 render。
- 修改人物音色：创建新 voice version/binding；历史 Edition 不变，新 Edition 只生成受影响句段。
- 修改停顿：创建新 settings snapshot/Edition，复用语音 render，只重建 Manifest 时间线和显式导出文件。
- 升级模型、Tokenizer、Normalizer 或后处理：按 fingerprint 精确失效。
- 归档人物：保留历史绑定，当前脚本重新分析时提示处理。

## 17. 失败恢复

| 故障 | 用户看到 | 权威数据 | 恢复 |
| --- | --- | --- | --- |
| Nano 未安装/损坏 | 模型未就绪 | 正文、脚本不变 | 校验并恢复下载 |
| Nano 执行后端不健康 | 朗读服务不可用 | 正文不变，任务留队 | 重启/切换后端、预热、重试 |
| 参考音频无效 | 音色测试失败 | 不锁定新版本 | 更换/修复文件 |
| VoiceGenerator 失败 | 候选生成失败 | 现有音色不变 | 重试或改用预设/上传 |
| 人物识别失败 | unknown 待复核 | 正文、人物不变 | 作者绑定后继续 |
| 云端未授权/已撤销 | 不调用云端，显示需复核 | 正文、人物不变 | 本地复核或重新明确授权 |
| 实际聊天模型不匹配 | 本次分析结果作废 | 旧脚本不变 | 修复 Provider 后重试 |
| 单句合成失败 | 章节部分完成 | 已成功句段保留 | 单句重试 |
| 任务进程崩溃 | 进度暂时停止 | 持久 job/render 保留 | 租约过期后恢复 |
| 正文已修改 | 旧版本提示 | 旧音频和 revision 保留 | 旧版播放或新建脚本 |
| 磁盘不足 | 暂停生成并提示 | 不删除重要资产 | 清缓存/扩容后重试 |
| 音频转码失败 | 目标句段未 ready | 已校验 master 可恢复 | 重试播放副本转码，不重合成 |
| Manifest 中间句缺失 | 只能播放连续 ready 前缀 | 已完成 render 保留 | 优先重试缺失句，不静默跳过 |
| 浏览器断线 | 进度暂停显示 | 后台任务继续 | 按 job ID 恢复 |

## 18. 实施阶段

### 阶段 0：ADR、模型、音色包和质量尖峰

- 固定 Nano、Audio Tokenizer、ONNX、VoiceGenerator 和转码器 revision/hash；
- 补充 ADR：Nano 执行后端、模型进程安全边界、共享任务表、正文云端授权；
- 对进程内 ONNX、受管本机进程、Compose Sidecar 和浏览器试听候选运行同一基准；
- 测试中文数字、标点、多音字、中英混读、长句和内部切分；
- 测试 3/5/8/12 秒参考音频与清洁度；
- 测试 independent segments 的音色、语速、停顿、漏字、重复和接缝；
- 测试首包、RTF、取消、崩溃恢复和连续 30 分钟稳定性；
- 测试 VoiceGenerator MPS/可用本地路径以及 Nano 二次克隆保持度；
- 生成并人工锁定 24 槽位基础音色包，或确定具有授权的替代包；
- 冻结基准语料、参数、能力矩阵和 go/no-go 报告。

退出条件：四项均明确——Nano 物理部署、24 音色来源、浏览器分段播放方案、VoiceGenerator 可见/隐藏结论。未退出阶段 0 时只允许原型代码，不建正式迁移和产品 UI。

### 阶段 1：共享基础设施与数据

- `MossNanoTTSAdapter`、`VoiceDesignAdapter`、能力/健康/指纹契约；
- 模型下载、校验、预热、受管进程或 Sidecar 生命周期；
- 扩展 `media_assets` 与引用/保留/清理策略；
- `background_jobs`、租约、幂等、重试、死信和 `model_run_records`；
- 幂等隐藏 `tts_snapshot`，不推进 working copy 基线；
- 音色、设置快照、脚本版本、Edition、render、Manifest 迁移；
- `moss-models`、`novel-media`、Range/ETag；
- fake adapter、崩溃恢复、迁移升级/回退和 GC 集成测试。

### 阶段 2：声音和朗读设置

- `reading` 路由、总览和导航；
- 旁白、章节/分卷范围覆盖；
- 正文分析隐私模式和独立云端授权；
- 人物卡声音页签；
- 预设、上传、标准化、授权、试听和锁定版本；
- 24 槽位基础音色池导入、覆盖率和缺失提示；
- 人物专属/继承绑定与历史影响预览；
- 发音、停顿、音频和缓存管理；
- 空、加载、失败、模型缺失、授权和磁盘不足状态。

### 阶段 3：脚本、场景和选角

- Markdown/UTF-16 映射和 `segment_kind`；
- `character_aliases`、别名冲突和场景切分；
- 本地规则解析；
- 授权后的最小化云端补充归因；
- requested/actual model 与严格 schema/ID 校验；
- 匿名人物稳定键、合并、拆分和升级；
- 确定性通用选角与 scope 优先级；
- 情绪/表达标签和校准置信等级；
- 脚本版本、复核、审批和人工覆盖安全继承。

### 阶段 4：独立句段合成和同步播放

- Edition 创建和不可变设置快照；
- 版本化 render fingerprint 与 owner/workspace 缓存；
- 持久句段任务、优先级和单并发资源锁；
- master/播放副本校验和后处理；
- 渐进 Segment Manifest 与连续 ready 前缀；
- Web Audio 队列及双 audio 回退验证；
- `textarea` 只读朗读覆盖层；
- 句段高亮、滚动暂停/恢复、跳转、倍速和进度；
- 局部重生成、旧版本视图和正文 hash 屏障。

完成阶段 4 才达到核心“番茄式多角色朗读”可用范围。

### 阶段 5：文字生成音色产品化

- VoiceGenerator 受管执行后端和资源锁；
- 从人物资料生成可编辑描述；
- 多候选、试听、来源和不可变版本；
- Nano 克隆验证和私人音色库复用；
- M4 不达标时隐藏入口，不影响已锁定基础音色包和上传路径。

### 阶段 6：高级生产

- 人工确认的情绪音色变体；
- 群体声音混合；
- 全书批量生成和可恢复进度；
- 章节/全书显式导出；
- 发音批量校对和可选 ASR 回查；
- 音频质量报告、可达性 GC 和配额治理；
- Monaco decorations（若 Monaco 已单独落地并验收）。

## 19. 测试与验收

### 19.1 固定测试集

建立不含未授权文本的项目测试集，覆盖：

- 旁白；
- 前置/后置人物提示语；
- 双人和多人轮流对白；
- 省略主语；
- 内心独白；
- 匿名青年/中年/老人/儿童；
- 群体声音；
- 同一匿名人物跨章、相同泛称但实际不同人物；
- Markdown、emoji、嵌套引号和特殊标点；
- 多音字、人名、年代和中英混合；
- 正文中途修改和音色换版。
- 用户手动滚动、键盘播放和正文 hash 不一致；
- 云端未授权、已授权、撤销授权和实际模型不匹配。

### 19.2 自动化门槛

- 明确姓名+说话动词样本的说话人识别目标不低于 98%；
- 非允许 character ID 数量为 0；
- 所有 unknown 和低置信度句段均可见、可编辑；
- 未修改 revision 的句段高亮偏移错误为 0；
- emoji/组合字符测试的前后端范围完全一致；
- 同幂等键不重复创建 job、render 或媒体；
- 相同正文重复点击朗读不重复创建可见 checkpoint，也不推进 working copy 基线；
- 单句修改只失效必要 render；
- 已审批脚本不可原地修改，同一脚本可创建多个独立 Edition；
- 正文修改后旧 manifest 不映射新正文；
- `local_rules_only` 网络捕获中正文外发数量为 0；
- `cloud_assisted` 未授权调用数量为 0，授权后 payload 只包含不确定窗口和允许候选；
- 实际聊天模型与请求配置不匹配时分析结果作废；
- `partial_ready` 只播放从首句开始的连续 ready 前缀，不跳过中间失败句；
- 任务崩溃恢复不重复合成已 ready 句段；
- 音色归档、角色归档和缓存清理不破坏历史引用；
- 普通清缓存不删除上传原件、标准化参考音频或锁定音色；
- 私人正文/音色 render 不跨 owner/workspace 复用；
- TTS 失败不改变 working copy 和 revision。

### 19.3 本机性能门槛

阶段 0 先记录真实基线；初始项目目标为：

- Nano 预热后标准中文实时因子 `RTF <= 1.0`，否则必须证明渐进生成仍满足产品体验；
- 单任务峰值内存不导致 16 GB M4 明显换页或拖垮 QwenPaw；
- 已缓存句段可立即播放；
- 连续 ready 前缀达到阶段 0 冻结门槛后可开始播放；
- 局部重生成不触发整章 TTS；
- VoiceGenerator 与 Nano 默认不同时常驻。

性能未达标时先优化部署、量化、加载和队列；不能通过删除版本校验、缓存正确性或复核流程换取速度。

### 19.4 人工听感验收

- 正式人物跨章可辨识且稳定；
- 旁白与主要人物明显可区分；
- 同场景路人不过度撞声；
- 无严重漏字、重复、爆音、噪声和异常停顿；
- 人物间响度基本一致；
- 独立句段接缝没有不可接受的爆音、吞字或长空白；
- VoiceGenerator 候选只有作者锁定后才能用于正式章节。

时长、解码和响度检查不能发现所有漏字、重复和错读。阶段 0/4 必须对固定样本人工听检；阶段 6 可增加 ASR 回查作为质量告警，但 ASR 结果不能自动改写正文或朗读脚本。

## 20. 发布门槛

核心功能进入默认可见前必须满足：

1. 阶段 0 真实 M4 报告完成；
2. 24 槽位基础音色包或等价授权音色来源完成验收；
3. 数据迁移具有升级和回退测试；
4. Nano 执行后端不影响 QwenPaw 原生聊天、模型、Skills、MCP 和插件管理；
5. `local_rules_only` 和 `cloud_assisted` 授权边界均通过网络/契约测试；
6. 一章真实多角色正文完成脚本复核、多 Edition、局部重生成和句段跟随；
7. `partial_ready` 连续前缀可播放，中间失败不会被跳过；
8. 关闭重开后任务、音色、Edition、Manifest 和进度可恢复；
9. 修改正文后旧高亮不误用；
10. 清缓存不会删除参考录音或锁定音色；
11. 至少完成旁白、正式人物、匿名人物和通用音色四类真实验收；
12. 所有 P0/P1 数据安全、声音授权和版本一致性问题清零；
13. 关联 ADR、总体架构、迁移、API、测试和回退说明同步更新。

## 21. 仍待验证

- Nano 进程内 ONNX、受管本机进程和 ARM64 Sidecar 在本机的真实差异及最终选择；
- 浏览器 ONNX 是否只保留为试听候选，以及 QwenPaw 宿主 CSP、缓存和内存限制；
- 最适合中文人物克隆的参考音频时长、内容和清洁度；
- Nano 跨句 rolling prompt 对一致性、重复和速度的净影响；它不阻塞首版 `independent_segment`；
- Nano 可可靠使用的中文发音控制形式；
- VoiceGenerator 在 M4 16 GB 上的 MPS 兼容性、速度和峰值内存；
- VoiceGenerator 样音经 Nano 二次克隆后的音色保持度；
- 24 槽位基础音色包的授权、听感去重和质量基线；
- Web Audio 分段队列与双 `<audio>` 回退的接缝差异；
- segment master 和浏览器播放副本的最终编码；
- QwenPaw 固定版本的 PawApp 模型设置 schema 是否足以承载模型路径、缓存目录和高级参数；
- `textarea` 只读覆盖层的精确视觉方案；
- Monaco 在宿主 Blob bundle 环境完成兼容验证后的切换时机。

这些验证项必须有显式回退：核心技术链可使用“上传/已授权锁定音色 + Nano ONNX + 本地规则/人工复核 + 独立句段同步”；但缺少完整基础音色包时只能发布有限音色预览，不能把完整通用选角标为完成。VoiceGenerator 产品 UI、复杂情绪、rolling prompt 和群体混音不阻塞核心链路。

## 22. 最终验收流程

```text
进入书本“朗读”
  -> 选择本地规则或明确授权智能增强
  -> 配置旁白
  -> 校验 24 槽位通用音色池
  -> 给主要人物配置专属声音
  -> 打开章节并保存正文
  -> 复用 revision 或创建隐藏幂等 TTS 快照
  -> 生成 revision 绑定的朗读脚本版本
  -> 自动识别旁白、正式人物和匿名人物
  -> 自动选角
  -> 作者复核低置信度句段
  -> 审批不可变脚本版本
  -> 冻结设置/发音/音色并创建 Edition
  -> Nano 独立句段合成并复用缓存
  -> 连续 ready 前缀形成渐进 Segment Manifest
  -> 播放到哪一段，编辑器高亮到哪一段
  -> 修改一句只重生成必要内容
  -> 旧 Edition 可回放，新 Edition 精确生成
  -> 关闭重开后恢复任务、Manifest 和播放进度
```

只有上述链路在真实 M4、真实数据库、真实浏览器和真实中文小说章节中完整通过，才可将本方案状态改为“已实现”。
