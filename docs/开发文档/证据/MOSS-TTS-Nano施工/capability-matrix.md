# T0 能力矩阵

状态：**T0-GATE 历史能力矩阵，经 2026-08-27 个人本地单用户产品范围裁决覆盖；阶段自动化结论不等于人耳质量或产品门禁通过。**

更新时间：2026-08-27（Asia/Shanghai）。

范围覆盖说明：本矩阵保留 T0-GATE 的历史技术结论，但其中原定“200% 后移 T4-GATE”的 UI 条件已被 2026-08-27 的用户最终裁决取代。当前 TTS 发布验收且仅覆盖 `1920×1080 × 助手收起/展开` 与 `2560×1440 × 助手收起/展开` 四个精确组合；低于 1920×1080、移动、窄屏和 200% 等效小视口不再是 T4 测试项或发布阻断项。

官方预设范围覆盖说明：T0-E 原“16/18 隔离测试、公众人物排除、分发／商用／生产 0”只保留为历史审计。固定 ONNX manifest/catalog 的 18 项依然保留 `official_preset` 技术兼容与溯源，但现行个人本地产品目录仅为六个中文预设：`onnx.Junhao`、`onnx.Zhiming`、`onnx.Weiguo`、`onnx.Xiaoyu`、`onnx.Yuewen`、`onnx.Lingyu`。18 项底层目录不等于当前 UI 目录，也不进入本轮中文专项质量与发布门禁。

## 状态词

- `GO`：精确技术契约可由下一阶段消费；不自动启用产品入口。
- `CONDITIONAL`：只允许在列明开关、回退和后续门禁下继续。
- `HOLD`：仍有未闭合 P0，不得作为下一阶段输入。
- `NO-GO/HIDE`：当前证据已足以否决或隐藏该候选；以后只能由新证据和新门禁重开。
- `NOT_REVIEWED`：没有真实审听人结论，不能用自动信号检查替代。

## 能力与证据

| 能力 | 技术状态 | 人工听感 | 产品默认 | 当前冻结结论 / 下一门禁 |
| --- | --- | --- | --- | --- |
| 固定源码、模型、Tokenizer、Python/Node 依赖 | `GO` | 不适用 | 不直接可见 | 固定 revision/tree/file hash 与隔离环境可重建；正式运行依赖仍由 T1-DEP 单一 Owner 接入 |
| macOS arm64 managed worker | `GO_DIAGNOSTIC_ONLY` | `NOT_REVIEWED` | 关闭 | 真实取消、SIGKILL、新 generation、ready 复用和修复版 1800 秒耐久通过；不能冒充 Linux 容器部署 |
| Linux/arm64 私网 Sidecar | `GO_TECHNICAL_FOR_T1_DEP` | `NOT_REVIEWED` | 关闭 | 固定 image/wheels/FFmpeg、零 host port、窄 token/bytes 协议、只读模型、故障/恢复/容器重启、1804 秒耐久、最终清理与 QwenPaw 健康真证据通过；只放行 T1-DEP，不表示生产服务已接入 |
| Nano 中文 20-case 技术矩阵 | `GO_TECHNICAL_ONLY` | `NOT_REVIEWED` | 关闭 | 20/20 技术 case、同 worker 3 probe、严格 hash/事件、RTF/RSS 已通过；漏字、错读、停顿与音色稳定尚无人听 |
| 3/5/8/12 秒 reference clone | `GO_TECHNICAL_ONLY / NO-GO_PRODUCT` | `NOT_REVIEWED` | `reference_clone_visible=false` | 仓库外 isolated-test-only 输入已严格核对顺序、字节、SHA、格式和时长，Linux 真容器 4/4 技术 recheck 通过；产品权利、正式 fixture 与人听仍未通过，不得把上传音色称为已可用 |
| VoiceGenerator 文字描述造声 | `NO-GO/HIDE` | `NOT_REVIEWED` | `voice_generator_visible=false` | 固定资产约 10.566 GiB，16 GiB M4 的 CPU FP32 静态余量不安全；没有真实加载/生成/二次克隆 |
| 24 槽通用音色包 | `NO-GO/HIDE` | `NOT_REVIEWED` | 自动通用选角关闭 | 24 个槽/48 个候选 ID 仅是契约；真实资产、权利通过、质量通过、production-ready 均为 0 |
| 固定 ONNX 官方预设声音 | `GO_LOCAL_PERSONAL_DIRECTORY_6 / REAL_NANO_BASELINE_READY / HOLD_PRODUCT_GATE` | 三个当前绑定已人工接受；目录整体不冒充全量听检 | 六个中文 `official_preset` 为当前产品目录；公开能力开关仍等待 GATE | 产品目录精确限于 Junhao、Zhiming、Weiguo、Xiaoyu、Yuewen、Lingyu。旁白 `onnx.Zhiming`、林晚 `onnx.Xiaoyu`、沈川 `onnx.Junhao` 已实际 `locked + accepted + bound`；fanout 修复后的真实 baseline request／Edition 与 56/56 Manifest 已 ready。18 项 manifest/catalog 只作底层兼容与溯源；最终听检与 T4-GATE 尚未通过。 |
| CodeMirror 6 编辑器候选 | `CONDITIONAL` | 不适用 | `editor_production_enabled=false` | 隔离 UTF-16/decoration/gutter/undo/Blob 原型通过；固定宿主保存链、系统 IME、可访问性与精确四组合留到 T4-GATE；textarea 保持当前编辑保存基线；200% 已非当前 T4 门禁 |
| Manifest v2 wire contract | `GO_FOR_T1_T4_CONTRACT` | 不适用 | 播放器关闭 | 唯一 snake_case schema、TS parser、正反 fixture、0-based ordinal、revision>=1、server-authoritative ready 派生和 URL/hash/ETag 门禁已通过 24/24 + 21/21；只冻结输入，不代表 endpoint 已实现 |
| Range/ETag 与分段调度算法 | `GO_FOR_T1_E_CONTRACT_ONLY` | 独立相邻句段 `NOT_REVIEWED` | `product_player_enabled=false` | 隔离 Range/ETag/CAS 和 Web Audio/双 audio 调度通过；正式鉴权、持久 CAS、流式读取、固定宿主与接缝人听留到 T4 |
| 随机跳播 ready-window | `GO_FOR_CONTRACT / CONDITIONAL_PRODUCT` | 不适用 | 关闭 | 策略冻结为连续 3 段且 8 秒，或到章末全部 ready；服务端回传、客户端按 segments+buffer_policy 严格复算，正式调度/播放器仍由 T4 验收 |
| 复核策略、blocker taxonomy 与 request/Edition guard | `ACCEPT_FREEZE_INPUT / NOT_IMPLEMENTED` | 不适用 | 无产品入口 | T0-H 十项决策已按固定 hash 接纳；由 T1-A fixture/DTO → T1-D schema 串行落地，不能写成已实现 |
| FFmpeg master/playback 链 | macOS `GO_DIAGNOSTIC_ONLY`；Linux `GO_RUNTIME_INPUT_FOR_T1_DEP` | 浏览器可播放，不等于听感 | 关闭 | macOS WAV→FLAC→AAC-LC/M4A、失败不发布与 bit-exact 恢复通过；Linux 固定 FFmpeg 9.0.1 窄 LGPL 运行时已进入固定 Sidecar。正式 Linux 转码发布链、浏览器矩阵与许可交付仍由 T1/T4 验收 |

## 现行 T4 有限核心产品矩阵

| 能力 | 当前状态 | 现行裁决 |
| --- | --- | --- |
| 本地规则人物归因与三角色配音 | `REAL_NANO_BASELINE_READY / HOLD_UNTIL_T4_GATE` | 只使用个人本地单用户路径和六个中文产品预设；三个当前绑定已锁定／接受／绑定，真实 baseline 与 56/56 Manifest 已 ready，最终听检和 T4-GATE 仍 HOLD |
| 网页分段播放器、CodeMirror 句段同步、段落／光标跳播、倍速／进度、更新朗读 | `REAL_EDGE_INTERACTIONS_READY / HOLD_UNTIL_T4_GATE` | 真实固定 Edge 四桌面组合、CodeMirror、跳播、控制、latest-wins、媒体 HTTP 和编辑零 TTS 写已通过；真实 pending gap、恢复和最终 GATE 仍待完成 |
| 恢复、最小缓存／磁盘保护、30 分钟稳定性、四桌面组合、安装／升级／卸载非回归 | `HOLD_UNTIL_T4_GATE` | 全部保留为现行 completion/gate，不可被范围缩减略过 |
| 云端辅助说话人识别 | `HOLD / PENDING_USER_DECISION` | 不进入当前本地产品默认路径；未经新裁决不得翻转 |
| 高级匿名人物身份／自动选角 | `HOLD / PENDING_USER_DECISION` | 不阻断旁白+两名正式人物有限核心，也不能随核心顺带放行 |
| 商业／再分发审批、英语／日语质量专项、云端／远程／共享／复杂继承 | `SUPERSEDED_OR_NON_TARGET` | 不是当前个人本地产品的前置、质量范围或阻断项 |
| OS controller/signing service、SSHSIG、正式 key，章节／全书音频导出 | `SUPERSEDED_OR_NON_TARGET` | 历史安全实验和导出设想可保留，但不进入当前产品或 T4-K/T4-GATE |

## 产品开关基线

```json
{
  "narration_product_enabled": false,
  "product_player_enabled": false,
  "editor_production_enabled": false,
  "generic_voice_pool_enabled": false,
  "automatic_generic_casting_enabled": false,
  "official_preset_source_enabled": false,
  "reference_clone_visible": false,
  "voice_generator_visible": false,
  "browser_onnx_preview_enabled": false
}
```

这些值是当前尚未通过产品 GATE 的安全基线，不是对个人本地使用的权利否决。`official_preset_source_enabled=false` 在现阶段只表示六个中文产品目录尚未通过真实章节与产品 GATE，不能否定其已冻结的产品范围，也不能把底层 18 项兼容目录扩张为 UI 目录；不得使用商业授权、明星／公众人物标签或历史 T0-E `no-go` 作为关闭原因。只有相应阶段 Owner 落地、测试和 GATE 明确接收后，才能翻转真实开关；不得用前端隐藏代替服务端与数据库约束。
