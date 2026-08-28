# T4-C 音频校验、接缝处理与转码

状态：**`IMPLEMENTED_CANDIDATE_WITH_REAL_LISTENING_HOLD`（2026-08-27）**。数据库/网络无关的 48 kHz 双声道 PCM16 校验、确定性响度/峰值处理、3 ms 句段接缝淡化和固定 FFmpeg 转码适配已实现；真实模型输出的独立相邻句段听检与固定宿主 FFmpeg 运行仍须 T4-K/T4-GATE。

## 1. 冻结处理链

```text
Nano PCM WAV bytes
  → 完整容器/格式/大小/时长校验
  → 静音、削波、RMS、峰值与可选时长漂移检查
  → 确定性增益 + 峰值限制 + 首尾 3 ms fade
  → canonical 48 kHz / stereo / PCM16 WAV
  → 固定路径 FFmpeg：FLAC master + AAC-LC M4A playback
  → 仅在明确缺少 AAC encoder capability 时允许 WAV playback fallback
  → ffprobe 编码/采样率/声道/时长与 bounded bytes 复核
```

处理模块不导入 SQLAlchemy、数据库模型、网络客户端或 Sidecar；转码不使用 shell，临时文件只有完整校验后才交给上层不可变发布。

## 2. 实际验证

```text
.venv/bin/python -m pytest tests/narration/test_audio_pipeline.py -q
13 passed
```

覆盖：确定性输出、格式拒绝、静音、削波、时长漂移、接缝 fade、FLAC/AAC 探测、明确 AAC capability fallback、一般转码失败不误降级、错误 probe 和数据库依赖隔离。

## 3. 仍为 HOLD

- 当前只使用 fake command runner 证明 argv、边界与失败语义；真实固定 FFmpeg 的编码可用性、许可证/镜像重建和实际文件听检尚未完成。
- WAV fallback 是能力缺失时的显式降级，不得吞掉磁盘、权限、损坏输出或一般 FFmpeg 失败。
- T4-GATE 前不得把响度、接缝或播放格式表述为已通过真实小说章节验收。

## 4. 文件摘要（本次候选）

```text
backend/narration/audio_pipeline.py             4bf53eb07cb2cce1afc44ca3ea656b9bef6c5a7d671d00d2a550cc0fe4286590
backend/narration/transcoding.py                ec445d2dda815eeeff519dfc96ef420dcac22da1174f16e1d93b561d532fd1f0
tests/narration/test_audio_pipeline.py          e62bdc2fc68bf3abcffe778f0162fe512e5362287b29667e997f3f9b6a94e70b
```
