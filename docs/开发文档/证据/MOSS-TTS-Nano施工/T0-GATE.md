# T0-GATE：阶段 0 汇合报告

状态：**PASS_WITH_EXPLICIT_NO-GO_CAPABILITIES。阶段 T0 已于 2026-08-26 通过；下一且唯一 ready set 为 `T1-DEP`。本结论只放行依赖/运行层接入，不表示任何朗读产品能力已经实现或可见。**

日期：2026-08-26（Asia/Shanghai）。

唯一集成 Owner：`/root`。本文件只由主代理维护；工作包完成不等于本门禁通过。

> **现行个人本地版覆盖说明（2026-08-27）：** 本报告记录的阶段 0 原裁决及 `T0-evidence-manifest.json` 所指向的原始快照／hash 继续作为不可变历史接纳证据；后加的范围覆盖注释不重算或冒充这些旧 hash。其中 `T0-E ACCEPT_NO-GO`、16/18 隔离上限、公众人物排除及“官方预设隐藏”只反映当时的商业发布／再分发和 24 槽生产包门禁，不再限制个人本地版。固定 ONNX manifest 的全部 18 个官方预设均可作为 `official_preset` 用于本地展示、试听、绑定、合成和播放，包括 `Trump`、`Xiaoyu`；T4-K 也不再要求三份用户上传录音。现行覆盖规则见 [个人本地版官方预设裁决](./T0-E/local-personal-official-presets.md)。

## 1. 最终裁决

T0-A…T0-I 的固定依赖、Linux/arm64 私网 Sidecar、真实 Nano 故障/容器重启与 1800 秒耐久、20-case 技术质量矩阵、reference-audio 窄 bytes 协议与 3/5/8/12 秒真实技术 recheck、编辑器/播放器隔离原型、数据安全契约和测试工具均已形成可复核输入。最终复验关闭了本阶段全部执行 P0：

1. Linux/arm64 Sidecar 使用固定 `linux/arm64` 镜像、固定 aarch64 wheels 与 FFmpeg 9.0.1 窄 LGPL 运行时，私网零主机端口、非 root、只读 rootfs/模型/源码、无数据库/媒体挂载；真实普通/参考请求、取消、活动请求 SIGKILL、恢复、新 generation 和容器重启均通过；
2. 1804.466 秒真实 Sidecar 耐久完成 750 个请求、0 失败、单一 PID/generation、0 restart；退出后 0 容器、0 TTS 进程、0 orphan/`.part`，QwenPaw 健康；
3. reference recheck 严格核对 3/5/8/12 秒四个仓库外隔离输入的顺序、字节数、SHA-256、48 kHz 双声道 16-bit PCM WAV 与精确时长，4/4 真容器请求通过；产品权利和人工听感仍未通过，因此只接收技术协议，继续冻结 `reference_clone_visible=false`；
4. 所有根状态、ADR 与阶段索引已经对账；最终证据 hash 清单为 [`T0-evidence-manifest.json`](./T0-evidence-manifest.json)，其 SHA-256 是 `5a65e4d939b2ab39e26948964f0f0ada9aaaa8e8e8b5a7934e837ff7eac254e9`。清单明确区分 T0-C 历史单例 smoke 与最终 20-case 技术矩阵。

人工听感、24 槽音色权利/质量、VoiceGenerator、正式 CodeMirror/播放器、正式媒体 API 和用户可见 reference clone 均不因技术原型通过而获得产品批准。它们分别保持 `NOT_REVIEWED`、`NO-GO/HIDE` 或 `CONDITIONAL_CONTRACT_ONLY`，并继续由后续产品阶段门禁控制。

## 2. 工作包接收状态

| 工作包 | 当前接收 | 说明 |
| --- | --- | --- |
| T0-A | `ACCEPT_TECHNICAL` | 固定来源、隔离依赖、许可证分层和 macOS 转码技术链；Linux 转码由 Sidecar 补证 |
| T0-B | `ACCEPT_TECHNICAL_FOR_T1_DEP` | macOS managed worker 只作诊断；固定 Linux/arm64 私网 Sidecar、真实 smoke/reference/fault/restart、1804 秒耐久和最终清理通过 |
| T0-C | `ACCEPT_TECHNICAL_ONLY` | 20/20 技术矩阵通过；reference 4/4 Linux 技术 recheck 通过；产品权利与人工听感未通过，用户入口保持关闭 |
| T0-D | `ACCEPT_NO-GO` | 接受 `voice_generator_visible=false`，不批准模型下载、正式依赖或 UI |
| T0-E | `ACCEPT_NO-GO` | 历史接纳只针对 24 槽契约／商业发布与再分发台账；真实 24 槽音色包为 0，自动通用选角关闭。它不否定个人本地 18 项 `official_preset` 的可用性 |
| T0-F | `ACCEPT_CONDITIONAL` | CodeMirror 是唯一正式候选；textarea 是当前保存基线；产品编辑器关闭到 T4-GATE |
| T0-G | `ACCEPT_CONDITIONAL` | 唯一 Manifest wire contract、24/24 TS 与 21/21 Range/ETag 通过；正式 API/播放器/人听仍关闭到 T4 |
| T0-H | `ACCEPT_AS_FREEZE_INPUT_ONLY` | 十项安全决策按固定 hash 接纳，只作为 T1-A/T1-D 串行输入，不代表 schema/API 已实现 |
| T0-I | `ACCEPT_TECHNICAL` | fixture/报告器/隐私证据契约可复用；`passed` 只表示技术检查 |

### 2.1 T0-H 精确冻结接纳

T0-GATE 对 [`T0-H/gate-decisions.md`](./T0-H/gate-decisions.md) 的 2026-08-26 原始快照作 `ACCEPT_UNCHANGED`，该历史冻结快照 SHA-256 为 `2437be4e13e182aae554cb853f16afbc0b475d51848ce2d413eb4c3d9076e283`。2026-08-27 只在 Markdown 外层增加官方预设适用范围覆盖，不改动或重算这项历史 hash；以下审查项仍按原快照的精确字段、状态、Owner 顺序、负向测试和阶段归属接纳：

```text
H-P0-01 H-P0-02 H-P0-03 H-P0-04 H-P0-05 H-P0-06
H-P1-01 H-P1-02 H-P1-03 H-P1-04 H-P1-05
H-P1-06 H-P1-07 H-P1-08 H-P1-09 H-P1-10
```

这项接纳只冻结 T1-A/T1-D 及后续阶段的唯一施工输入，不代表 ORM、迁移、API、worker、媒体、隐私或卸载控制已经实现。若后续需要改变任一项，必须退回本 GATE/ADR 重新裁决并生成新 hash，不能由并行工作包自行解释或复制第二套 schema。

## 3. 七项 go/no-go

| 决策项 | 当前值 |
| --- | --- |
| Nano 物理部署 | `GO_TECHNICAL_FOR_T1_DEP / LINUX_ARM64_PRIVATE_SIDECAR` |
| 24 音色来源 | `NO-GO/HIDE` |
| 浏览器分段播放方案 | `CONDITIONAL_CONTRACT_ONLY / product_player_enabled=false` |
| VoiceGenerator | `NO-GO/HIDE` |
| 正式编辑器与安全降级 | `CONDITIONAL_CODEMIRROR6 / TEXTAREA_BASELINE / editor_production_enabled=false` |
| 随机跳播 ready-window | `GO_FOR_CONTRACT / CONDITIONAL_PRODUCT` |
| 复核策略/阻断分类 | `ACCEPT_FREEZE_INPUT / NOT_IMPLEMENTED` |

精确技术/听感/可见性状态见 [capability-matrix.md](./capability-matrix.md)。

## 4. 降级与回退

- TTS 专项尚未接入生产；当前最安全回退仍是保持全部产品开关 false，不改正文、不建迁移、不注册路由/工具。
- VoiceGenerator、完整 24 槽通用音色池、reference clone 与浏览器 ONNX 在该历史 T0 产品状态下默认隐藏。原“官方预设试听／安装隐藏”结论已被 2026-08-27 个人本地裁决覆盖；当前官方预设 capability 只能因目录未安装、固定 hash／fingerprint 未核验、实际推理失败或后续产品 GATE 未完成而保持关闭，不能因商业授权或人物标签关闭。
- CodeMirror 门禁失败时继续使用现有 textarea 保存/CAS/recovery 链；不创建视觉叠层。
- T1-DEP 接入或重建复验若无法维持已冻结 Sidecar 边界，立即关闭 TTS capability 并退回 T0 固定镜像/模型输入；不得以 macOS worker 冒充容器生产拓扑。
- 原型、模型和媒体均不进入 PawApp 包；模型/媒体外部目录由各证据记录单独治理。

## 5. 下一 ready set

当前：**仅 `T1-DEP`**。T1-A…T1-G 尚未 ready；它们必须继续遵守依赖冻结与唯一迁移 Owner 顺序。

后续形成 ready set 的串行骨架为：

```text
T1-DEP
  -> T1-A contracts / taxonomy fixture
  -> T1-D unique ORM + Alembic owner
  -> T1-B / T1-C / T1-E / T1-F
  -> T1-G
  -> T1-GATE
```

`T1-DEP` 只允许把固定 Sidecar/转码/运行依赖接入项目可重建层并完成对应验证；不得提前创建 TTS 生产 schema、API、路由、播放器或 UI。只有 T1-DEP 自身验收通过，才可放行 T1-A 的公共常量、DTO、taxonomy fixture；T1-D 仍是唯一 ORM/Alembic Owner。

## 6. 后续非阻断门禁

以下不是 T0 执行 P0，但在相应用户可见能力启用前仍是硬门禁：

- Nano 中文与独立相邻句段的人工听感：`NOT_REVIEWED`；
- reference clone 的正式权利记录、产品 fixture 与人工听感：`NO-GO_PRODUCT`；
- 24 槽真实音色资产、可再分发/商用权利、去重与人听：`NO-GO/HIDE`；这是完整通用选角包的独立门禁，不影响 18 项官方预设的个人本地使用；
- VoiceGenerator 真机安全余量、真实候选与二次克隆：`NO-GO/HIDE`；
- 固定宿主 CodeMirror、系统中文 IME、200%、长章、可访问性：T4 启用门禁；
- 正式鉴权/持久 CAS/流式 Range、独立句段接缝与播放器清理：T4 启用门禁；
- FFmpeg 源码 PGP 链、Safari/Firefox/移动端与再分发义务：T1-DEP/后续 UI 门禁。
- 原 Linux smoke/1804 秒耐久记录的 runner SHA-256 为 `e5bbb1d…`，当前加固后 runner 为 `db396d7…`，旧脚本源码未保留，故原始编排不能逐字节精确重放；这不阻断只接入依赖/Compose 的 T1-DEP，但 T1-B 在宣称运行门禁可重放前必须恢复旧快照，或用当前固定 runner 重跑 fault/restart 门禁。

## 7. 用户批准

用户已于 2026-08-26 明确授权按本专项 T0–T6 目标模式完整实施，并允许按当前开发文档内的子代理并行设计施工。该授权允许前一阶段门禁通过后继续，但只允许消费本门禁列出的 `T1-DEP` ready set，不允许绕过后续门禁或扩展到其他开发文档；无需为已批准范围重复询问，但任何新增产品范围、破坏性数据动作或无法安全降级的 P0 仍需重新裁决。
