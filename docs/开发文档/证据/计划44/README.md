# 计划 44 实施与隔离验收记录

日期：2026-08-31（Asia/Shanghai）

裁决：**V1.4 二次复查缺陷已修复；修复后关键路径已随计划 47 复验折叠语义、Space 单选、失败降级、抽屉焦点和移动遮罩。计划 44 的完整页面／网络矩阵、原生 radio 方向键和长期部署仍未完成。**

## 1. 候选身份与隔离边界

- 施工开始基线：`4cb0d47`；施工期间主工作区由其他已提交任务线性前进到 `3d9dd0c`，最终候选按当前工作树重新构建，不覆盖或回退其他改动。
- V1.3 候选目录文件摘要：`75e6af4466057530b33723325af5c8922d310c4a3b5ad63899d75d99090599e8`。
- V1.3 前端 bundle SHA-256：`1ec2bbb50760dc64892288f480e322053dbe260bd977fde88f401cef09eec246`。
- 上一轮隔离入口为 `127.0.0.1:18144`，验收后已清理；隔离小说《雾港回声》，人物“许棠”。名称和内容均不使用“测试”字样。
- QwenPaw、PostgreSQL、插件数据、媒体、备份和 TTS 密钥均使用本轮独立容器／网络／命名卷；只读复用了既有 MOSS 模型卷。未挂载、读取或写入长期数据库、长期媒体和长期密钥。
- 隔离数据库迁移：`20260830_0035 (head)`；健康接口为 `ready`。Nano／人物匹配／高级调音／私人删除 readiness 可用；隔离容器没有原生 macOS VoiceGenerator host，因此该能力按契约 fail closed 为 `TTS_VOICE_GENERATOR_HOST_UNAVAILABLE`。

## 2. V1.3 自动化结果

| 检查 | 结果 |
| --- | --- |
| 计划 44 定向 Vitest（含 scope 竞态、降级与去重回归） | `10 files / 78 tests passed` |
| 完整前端 Vitest | `119 files / 1022 tests passed` |
| `pnpm typecheck` | PASS |
| `pnpm build` | PASS |
| `scripts/package_plugin.py` | PASS |
| manifest／Skill／QwenPaw 集成契约 | `127 passed` |
| `docker compose config --quiet` | PASS |
| `git diff --check` | PASS |

定向测试覆盖三个共享挂载入口、唯一 radio 写路径、试听／详情零绑定、当前项零写入、失败重试、live region、筛选计数、lazy advanced、scope 隔离、embedded 可访问名称和 dirty-aware footer。

## 3. 修复前浏览器验收（历史证据）

### 3.1 视口与布局

| 页面 | 视口 | 结果 |
| --- | --- | --- |
| 人物卡声音 | `2560×1440`、`1920×1080`、`1280×800`、`390×844` | 无页面／音色行横向溢出；标签页可见可切换；移动选择区约 `48px` 高 |
| 朗读官方音色库／人物目标 | `1920×1080`、`390×844` | 无重复 use button；窄屏试听／详情并排；目标人物可访问名称正确 |
| 人物配音面板 | `1920×1080` | 完成状态只出现一次；VoiceGenerator readiness 使用独立原因 |

实际验证结果：

- 中文、English、日本語筛选和英文／中文搜索均可恢复；搜索“深夜”得到 `1` 项，清空后恢复中文 `6` 项。
- 每行只有 radio、试听、详情；`.anw-official-voice-card__use` 数量为 `0`。
- 点击“CN 明星”后隔离人物绑定从未配置变为 version `1`；再次点击当前项保持 version `1`；选择“CN 机车”后只前进到 version `2`，没有双写。
- 当前 radio 保持 checked、可聚焦且没有 `disabled`；详情展开独占整行且不改变绑定。
- 高级区首次关闭时内部 body 数量为 `0`；首次展开后为 `1`，关闭后 DOM 暂态保留但不可见、不可聚焦且不进入语义快照。
- 声音标签 `dirty=false` 的 footer 只有“关闭”；在基础资料制造未保存草稿后，声音标签恢复“撤销修改／关闭／保存人物卡”及明确归属提示。
- `基础资料 → 本线档案 → 成长与状态 → 声音` 往返正常；Esc、顶部 X 和底部“关闭”均能关闭人物卡。
- 中文搜索输入可用；最终浏览器控制台 `warn/error = 0`。
- 页面加载、筛选、详情和当前项重复选择均未生成音频；试听与真实 VoiceGenerator 推理不属于本轮 UI 减重的写入验收。

### 3.2 浏览器工具限制

当前 in-app Browser 的键盘注入可以可靠触发 Esc，但对已聚焦的原生 radio 注入 Space／Arrow 时没有产生浏览器默认选择动作；绑定始终保持 version `2`，因此没有误把工具无响应写成产品通过。源码继续使用同名原生 radio group，没有自定义 keydown 拦截，相关结构和一次写入由定向测试覆盖。进入长期部署前仍需作者或人工浏览器执行一次 Space 与四方向键复核。

## 4. 浏览器发现并修正的问题

人物配音面板在“全部人物已配置”且 VoiceGenerator 不可用时，把 `batchAvailability.reason` 同时渲染为 roster 状态和 generator note，导致“所有人物均已配置声音”重复两次。修正后：

- roster 状态保留“所有人物均已配置声音。”；
- generator note 改用 `generateAvailability.reason`，显示 `人物专属音色生成暂不可用（TTS_VOICE_GENERATOR_HOST_UNAVAILABLE）。`；
- 新增回归测试，要求完成状态恰好出现一次且生成能力原因保持独立。

## 5. 截图证据

- [人物卡声音 1920×1080](./人物卡声音-1920x1080.png) — SHA-256 `92190431a009a0b1c37e7da75eaa560918856f1d1982e4133bd9910083be721d`
- [人物卡声音 390×844](./人物卡声音-390x844.png) — SHA-256 `0c96091bab8179123fb2acbc4a6a744cc70119b36029c37ffa4b98b4e2e24d80`
- [朗读官方音色库 390×844](./朗读官方音色库-390x844.png) — SHA-256 `887855ceb82de186071b668a3a009f44e6f2ce64a3e69db780fd57250cefc8b6`
- [人物配音提示修正 1920×1080](./人物配音提示修正-1920x1080.png) — SHA-256 `4a4c46ba8abcc6da9fc4103ffb63272cf6f6af073976b91fc895b5f6220423a9`

## 6. 部署与恢复裁决

- 未进入 `VUI44-DEPLOY`：本计划明确要求长期安装另行授权。
- 本轮隔离小说、绑定、数据库与媒体均属于一次性环境；清理隔离命名资源不会影响长期用户数据。
- 验收完成后已精确删除 `ai-novel-2026-ui44-*` 的 3 个容器、1 个网络和 6 个隔离卷；复查无同名前缀残留。共享只读模型卷 `ai-novel-2026-moss-models` 仍在，长期 QwenPaw、PostgreSQL 与 Sidecar 保持运行且 health 为 healthy。
- 长期部署前先完成 radio 人工键盘复核，再记录长期旧包／bundle hash、安装候选、只读检查 health、18 音色目录、四项能力及 QwenPaw 原生页面。

## 7. 2026-09-01 自查修复

修复内容：

- binding 与 profiles 改为独立完成、独立失败；profiles 失败不再丢弃已读取 binding，也不再隐藏 VoiceGenerator。
- 每轮投影使用小说／人物／reload 组成的 `projectionKey`；成功和失败提交都必须命中当前 key，旧人物请求晚失败不会进入新 scope。
- 人物卡父层成为 binding/profiles 的唯一正常路径读取者，官方音色子面板接收受控投影，只继续加载官方目录，不再重复读取同一 binding/profiles。
- 当前声音改为 `unbound / resolved / unresolved` 三态；已绑定但详情缺失时显示“需要恢复”，不再误报为“跟随规则”。
- 计划状态已纠正为 `VUI44-QA-BROWSER` 未闭合，不再把人工键盘缺口写成完整浏览器通过。

修复后验证：定向 `10 files / 78 tests`、完整前端 `119 files / 1022 tests`、typecheck、build、插件打包、`127` 项宿主契约、Compose 配置及 `git diff --check` 全部通过。由于上一轮隔离环境已经按计划清理，V1.3 尚未取得新的浏览器截图、网络记录或人工键盘证据。

## 8. 2026-09-01 二次复查修复（V1.4）

本轮关闭四项继续复查发现的问题：

- `CharacterVoiceCardPanel` 与匹配暂态使用 `novelId:characterId` scope；工作台同时以该 scope 设置 React key。旧人物请求在 scope 变化时取消，晚到结果还要通过当前 scope 与请求序列双重校验，不能进入新人物。
- “使用此音色”不再直通原始响应；人物卡和人物配音入口共同核对 preset、target kind、character 和版本形状，CAS 漂移继续进入可恢复冲突，不把错误身份当作成功。
- 当前请求收到其他作品／人物的 binding 时转入明确错误态，不再永久停在“读取中”。
- 人物工作区已有 binding 作为首次只读投影；无 binding 时形成 version `0` 的 unset 投影。任何使用、匹配或后续刷新仍重新读取权威 binding，并继续使用 CAS，避免以旧快照覆盖并发修改。

新增回归覆盖：已配置与未配置人物的首次 binding 零重复读取、写后重新读取、错误 binding scope fail closed、人物 A 的 `ready_unapplied` 晚到后不能在人物 B 显示或应用、待应用响应 preset 身份漂移必须拒绝，以及共享身份断言的正负用例。

V1.4 当前验证：计划 44 定向 Vitest `10 files / 84 tests passed`，完整前端 Vitest `122 files / 1049 tests passed`，TypeScript、生产构建、插件打包、`127` 项 manifest／Skill／QwenPaw 集成契约、Compose 配置及 `git diff --check` 均通过；最终 bundle SHA-256 为 `155417e6bfe6e4a5327cc6e32f60cc336b93cbdb444632c4cf1eaf03bb202035`。验证期间曾观察到计划 46 的 `CharacterWorkspaceV1`／`CharacterWorkspaceV2` 接线短暂阻断全局类型检查；等待其共享文件稳定后重跑已通过，本轮没有越界修改该类型边界。

## 9. 修复后浏览器复验（随计划 47）

- 人物卡声音页在 `1920×1080` 复验，标签可往返；VoiceGenerator 不可用时没有空的“生成专属音色”标题。
- 官方音色保持唯一 radio 绑定入口；Space 选择在隔离人物上产生一次写入。方向键注入受 in-app Browser 工具限制，未冒充通过。
- 高级区关闭时 body 为 `display:none`，可见后代焦点数为 `0`；再次展开仍可恢复。
- 全局人物配音抽屉 Escape 关闭并把焦点还给原“更换”按钮；`390×844` 全屏面板覆盖宿主侧栏且没有横向溢出。
- 隔离模型失败时显示可重试失败，不改变原人物绑定；刷新后能恢复同一命令。
- 新截图与完整结果见[计划 47 隔离证据](../计划47/README.md)。

本节只补充修复后关键路径，不把计划 47 分散在不同页面的四个视口冒充计划 44 要求的完整人物卡矩阵。
