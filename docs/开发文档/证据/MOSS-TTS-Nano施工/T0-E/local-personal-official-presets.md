# T0-E 个人本地版官方预设现行裁决

状态：**历史“18 项均进入个人本地产品”裁决；已由 2026-08-27 最新“底层 18 项保留、正式产品仅 6 个中文预设”范围裁决部分取代。**

> 现行覆盖：本文关于“不按公众人物、明星或商业授权状态排除 fixed manifest 行”的原则继续有效；但“18 项全部进入选择器／试听／绑定／合成／播放”的产品范围已经失效。当前产品只开放 `onnx.Junhao`、`onnx.Zhiming`、`onnx.Weiguo`、`onnx.Xiaoyu`、`onnx.Yuewen`、`onnx.Lingyu`，其余 12 项只保留 metadata-only 技术目录用于固定版本兼容、升级和排错。现行正式绑定为旁白 `onnx.Zhiming`、林晚 `onnx.Xiaoyu`、沈川 `onnx.Junhao`；不得再等待选择或沿用旧候选映射。

适用范围：AI小说世界2026 的个人、本机、自用、非商用运行。本文不批准把官方模型、预设音频、模型权重、prompt codes 或生成音频提交到 Git、随软件再分发、销售音色，或向第三方提供语音服务。

## 1. 权威优先级

1. 本文是个人本地产品对官方预设的现行裁决。T0-E 已有 `README.md`、`licenses.md`、`listening.md`、`voice-pack-manifest.json` 及 T0-GATE hash 证据继续保留，作为 **2026-08-26 商业发布／再分发风险审计的历史记录**。
2. 历史材料中的 `no-go`、公众人物排除、`Trump`／`Xiaoyu` 排除、16/18 隔离测试上限、中文 5/6 上限，只能用于说明当时的商业发布／再分发审计口径；不得继续限制个人本地版的展示、试听、绑定、合成或播放。
3. 商业发布、再分发和对外语音服务的状态继续记为“未评估／未批准”，但这些信息不得改变个人本地功能可用性。若未来改变产品用途，应另开范围明确的审计，不得反向改写本裁决或历史证据。

## 2. 固定官方来源

| 字段 | 固定值 |
| --- | --- |
| 官方 ONNX 仓库 | `OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX` |
| revision | `f52645cb467506d8e18e746ddd59482685b74e58` |
| manifest | `browser_poc_manifest.json` |
| manifest SHA-256 | `097d80e993dc29f0bae427590b4f77084a161cb578b50d82c29f455d5faa9eee` |
| 正式模型 fingerprint | `3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d` |
| 产品来源类型 | `official_preset` |
| 数据库兼容来源类型 | `VoiceProfileVersion.source_type=preset`；这只是既有存储枚举，不代表用户上传或用户原创 |

历史 T0-E 口径曾把固定 manifest 的 18 个精确 preset ID 全部纳入个人本地音色来源：

`onnx.Junhao`、`onnx.Zhiming`、`onnx.Weiguo`、`onnx.Xiaoyu`、`onnx.Yuewen`、`onnx.Lingyu`、`onnx.Trump`、`onnx.Ava`、`onnx.Bella`、`onnx.Adam`、`onnx.Nathan`、`onnx.Soyo`、`onnx.Saki`、`onnx.Mortis`、`onnx.Umiri`、`onnx.Mei`、`onnx.Anon`、`onnx.Arisa`。

这个 18 项列表现只作底层兼容和技术溯源，不是当前产品目录。当前选择器只如实展示 6 个中文官方预设；不对这 6 项设置明星、公众人物、可识别真人或名称排除名单。其余 12 项不进入当前 UI、专项质量验收或发布门禁，原因是已缩减的中文产品范围，而非人物标签或商业授权状态。

## 3. 身份、溯源与运行时规则

- 每个新建官方预设版本必须记录 `source_kind=official_preset`、官方仓库、revision、manifest 路径与 SHA-256、精确 preset ID、正式模型 fingerprint、该 preset 的 prompt-code 摘要及实现所需的不可变 hash。旧 `preset_catalog` 只作历史记录兼容；新记录不得继续写成 `preset_catalog`。
- 官方预设不得伪装为 `user_upload`、用户原创、VoiceGenerator 生成音色或已获商业授权。`source_type=preset` 与 `source_kind=official_preset` 必须同时可复核。
- Python Runtime 与 ONNX manifest 同名映射不一致时，以当前正式使用的固定 ONNX manifest、模型 fingerprint 和实际 preset ID 为唯一权威；禁止按名称、显示名、音频文件名或相似发音跨 runtime 猜测替换。
- 运行时只从固定官方来源取得所需模型，或使用模型内嵌 prompt codes。仓库只保存非敏感的来源元数据和 hash；官方预设音频、权重、完整 prompt codes 与生成音频均不得进入 Git、插件包或文档证据目录。
- 技术上只有以下情形可阻止单个预设：固定 revision 中不存在该 preset ID、prompt codes 缺失、manifest 与模型 fingerprint 不匹配、映射冲突无法消歧、资产损坏、校验失败或实际推理失败。商业授权未评估、明星／公众人物标签和可识别真人标签都不是个人本地版的阻断理由。

## 4. 产品与 capability 口径

- 历史“18 个预设全部进入选择器”的 capability 口径已失效。当前只有 `onnx.Junhao`、`onnx.Zhiming`、`onnx.Weiguo`、`onnx.Xiaoyu`、`onnx.Yuewen`、`onnx.Lingyu` 六项可用于展示、试听、旁白／人物绑定、章节合成和播放；18 项完整目录只保留非产品化技术元数据。
- capability 可以因为 catalog 尚未安装、固定 hash／fingerprint 未核验、Sidecar 未就绪、真实推理未通过或对应阶段 GATE 尚未完成而 fail-closed；错误原因必须是技术状态，不能继续使用 `PRESET_RIGHTS_NOT_APPROVED` 等商业权利原因。
- 24 槽通用音色包、VoiceGenerator 和用户上传 reference clone 均不在当前完工范围。当前真实章节验收只消费上述 6 个中文官方预设和已确认的三项绑定，不因此宣称已形成 24 槽自动通用选角包。
- 商业发布／再分发风险可在详情或审计页标记为“未评估”，但不得影响个人本地选择、试听、绑定、合成和播放。

## 5. T4-K 现行前置条件

- 删除“三份用户上传录音”与“六份 source/reference 媒体”的前置条件。
- 作者已完成选声、锁定和接受：旁白 = `onnx.Zhiming`、林晚 = `onnx.Xiaoyu`、沈川 = `onnx.Junhao`。这三项是当前真实章节验收的唯一权威绑定，不得再等待作者选择，也不得回退到 `onnx.Lingyu`／`onnx.Yuewen`／`onnx.Junhao` 旧候选映射。
- readiness 与权威审计必须证明三个版本均来自同一固定 ONNX manifest／revision／模型 fingerprint，三个 preset ID 互异，来源为 `official_preset`，并核验每个 preset 的 manifest/prompt-code hash；不得要求上传参考录音，也不得设置公众人物排除名单。
- 真实 Nano 一章已建立 `ready` baseline，但 30 分钟稳定性、四个精确桌面组合、播放器、CodeMirror、人工相邻句段／三角色听感及 T4-GATE 仍需独立完成。独立 controller authority、OS service、SSHSIG、正式 key 和远程证明已被裁决为 `REJECTED_NON_BLOCKING`，不是个人本地 T4-K/T4-GATE 前置。

## 6. 非目标与恢复

- 本裁决不删除、不改写历史 T0-E JSON/hash，也不把历史商业风险判断伪装成从未发生。
- 本裁决不批准低于 1920×1080 的 TTS UI 范围，不改变既有四桌面组合合同。
- 固定 manifest、revision 或模型 fingerprint 发生变化时，必须创建新的 catalog/version 和溯源记录；旧人物绑定、Edition 与生成资产继续绑定旧版本，不得按名称原地替换。
