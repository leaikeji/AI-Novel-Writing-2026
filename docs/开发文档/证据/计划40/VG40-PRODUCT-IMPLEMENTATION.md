# VG40-PRODUCT：产品闭环源码与隔离验收记录

状态：**2026-08-31 长期部署、正式人物 T7、四章 Edition 和真实浏览器验收已经完成，`VG16-PRODUCT=PASS`。作者听检仍未执行，因此 `VG16-FINAL=HOLD_AUTHOR_LISTENING`。**

## 已形成的产品闭环

- `0035` 在线性 `0034` 后新增 `voice_design_drafts`、`voice_generator_commands`、`voice_generator_run_evidence`，并封闭 VoiceGenerator 与 Nano 两条 ModelRun、生成资产、Voice Version、人物绑定和私人删除关系。
- 六个公共 API 已接入同一 `SqlAlchemyVoiceGeneratorService`；创建与重试受能力门禁约束，既有任务的查询、取消和已生成音色应用在宿主失联时仍可恢复，不增加试听、命名或版权确认门禁。
- 处理器复用 `moss-nano` 单槽，先证明 Nano 卸载，再调用 macOS 原生宿主；宿主退出后才执行 Nano 技术验证。失败、取消、CAS 漂移都不覆盖原人物声音。
- macOS 宿主固定 `moss-voice-generator-host/1`、两个官方 revision、MPS/BF16 分阶段拓扑和官方音频参数；只监听 `127.0.0.1:18765`，使用 Bearer token、内容寻址发布包和 launchd 管理。
- 宿主 token 只在仓库外 `0600` 文件和 QwenPaw 私有 secret volume 中各存一份；Compose 只传文件路径，不传 token 值。
- 人物卡组件支持一次点击生成、后台状态恢复、取消、一键重试、CAS 漂移后的“使用此音色”；宿主失联时仍展示已有任务，但隐藏新的生成和重试操作。

## 隔离验证

| 项目 | 结果 |
| --- | --- |
| `0034 → 0035 → 0034 → 0035`，临时 pgvector/PostgreSQL 18 | PASS |
| 生成成功、双 ModelRun、自动绑定、真实统一删除 | PASS |
| 人物版本漂移、绑定 CAS 漂移、宿主失败不可变留证 | PASS |
| 宿主协议、重启恢复、取消、音频下载与真实 HTTP 客户端 | PASS |
| macOS 固定模型快照逐文件 SHA-256 只读预检 | `READY`；未在本阶段重新加载模型 |
| Docker → `host.docker.internal` → macOS `127.0.0.1` | `REACHABLE` |
| VoiceGenerator/运行时/迁移/readiness 专项 | PASS |
| 前端 Vitest | 113 文件、981 项 PASS |
| 前端 typecheck/build | PASS |
| 插件打包与 manifest/Skill/QwenPaw 契约 | PASS |

隔离数据库与网络探针均在完成后销毁；没有操作长期数据库、长期媒体、正式小说或长期 PawApp。

## 自查中修复的缺陷

1. 失败宿主回执原先把宿主完成时间当作 ModelRun 创建时间，违反数据库权威时钟围栏；现将宿主时间保留在运行证据中，ModelRun 使用当前权威时钟。
2. `0010` 的旧媒体身份触发器会阻止 `0032/0034` 已确认的精确私人音色删除；`0035` 仅对已封存删除计划放行对应状态迁移，其他引用媒体继续不可变。
3. 产品运行时原先假定模型目录有简写别名；现直接绑定两个官方仓库名和固定 revision 的真实只读目录，不使用软链接。
4. 前端 API 原先只校验 DTO 形状，没有把 VoiceGenerator 响应闭合到请求 novel/character/command；现六条调用均验证服务端作用域。
5. 宿主失联原先会遮蔽已有命令；现只关闭新生成/重试，已有任务仍可查看、取消或应用已完成音色。

## 长期部署与正式人物闭环

- 长期 Alembic head 为 `20260830_0035`；QwenPaw、PostgreSQL 与 Nano Sidecar healthy，四项 narration capability（含 `voice_generator`）均为 `enabled/visible/actionable`。
- 正式小说《潮汐盲区》包含两卷四章、两位主角和五位配角；TTS 前后没有改写标题、卷章、正文或人物卡内容。
- 沈砚的 VoiceGenerator 命令 `b32afe0f-9bb0-4bc4-aead-caeeb56db3d6` 进入 `ready_applied`，generated Voice Version 为 `653ae852-ebdc-55d0-b582-7cf52dfa9f8f`，人物绑定版本由 1 单调更新为 2。
- 四章当前 Edition 分别为 `b0ca6d9a-9c44-4994-9ec5-1c982b7f5201`、`48927bc0-e7eb-4947-9be2-301bca37afd2`、`604e6ae5-ea2e-452b-b624-a5ac07097226`、`0475f56a-86ed-4c88-8fb3-e5bf072c16ee`，合计 `502/502` 句段 ready。
- `2560×1440`、`1920×1080`、`1280×800`、`390×844` 均完成播放器和人物卡真实浏览器复核；播放、暂停、前后句、进度、倍速、当前说话人、Edition 冻结音色及窄屏详情均可用，控制台无 warning/error。
- generated 音色出现在统一私人音色档案和删除影响投影中；依计划没有对正式人物音色执行物理删除。

当前只剩作者实际听检。未听检前可表述为“人物专属新音色已在长期环境生成、绑定并用于四章朗读”，但不能表述为“作者已经认可这条音色的主观效果”。
