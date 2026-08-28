# T0-D VoiceGenerator → Nano 二次克隆保持度协议

> 状态：**协议已冻结，真实执行 0 次，候选音频 0 份，人工听检 0 次。**<br>
> 本文是后续主代理持锁时的可执行记录模板，不是已通过的模型证据。

## 1. 目标与非目标

目标是回答两个独立问题：

1. MOSS-VoiceGenerator 能否在 Apple M4 / 16 GB 的受控子进程中生成可用的项目自有候选声音；
2. 候选声音被锁定为参考音频后，Nano 是否能在不丢字、不重复、不出现明显音色漂移的前提下保留其声线身份。

非目标：不模仿任何可识别真人，不使用用户小说正文，不向证据目录复制模型/音频，不让 VoiceGenerator 逐句参与正式朗读，不在同一 Python 环境混装 VoiceGenerator 和 Nano 冲突依赖。

## 2. 必须串行的锁与进程

```text
主代理冻结 revision/hash/外部目录
  |
  +-- 持有 LOCK-MODEL-ASSETS + LOCK-VOICEGEN
  |     |
  |     +-- 独立 VoiceGenerator Python 3.11 子进程
  |     +-- 生成候选 WAV 到仓库外媒体目录
  |     +-- 校验 WAV/hash/峰值内存/首包/RTF
  |     +-- 退出进程，确认模型不再常驻
  |
  +-- 释放 LOCK-VOICEGEN，确认 T0-B/T0-C 未持有 LOCK-NANO
  |
  +-- 持有 LOCK-MODEL-ASSETS + LOCK-NANO
        |
        +-- Nano ONNX 独立进程以候选 WAV 为参考
        +-- 生成同文本及留出文本的克隆版
        +-- 校验 WAV/hash/漏字/重复/音色漂移
        +-- 退出并释放 LOCK-NANO/LOCK-MODEL-ASSETS
```

`LOCK-VOICEGEN` 和 `LOCK-NANO` 不得同时持有；不得为“方便对比”同时常驻两个模型。任一进程无法在有界时间内退出时，本轮记为 `failed`，保留临时目录的可审计清单，不继续启动另一模型。

## 3. 前置门禁

| 门禁 | 必须证据 | 当前 |
| --- | --- | --- |
| VoiceGenerator 权重 | revision `97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4`，全部使用产物本地 SHA-256 通过 | **blocked：未下载** |
| Full codec | 将 `MOSS-Audio-Tokenizer` 精确 revision/两个权重 SHA-256 加入隔离锁并本地复核 | **blocked：只有官方元数据观测** |
| 隔离依赖 | Python 3.11 锁、hash-only 安装、`pip check`、导入测试 | **blocked：官方 CUDA 依赖与 Nano 锁冲突** |
| MPS/CPU 路径 | 一个后端在 M4 真实生成成功；记录实际 dtype/内存/速度 | **blocked：官方示例只分支 CUDA/CPU** |
| 资源安全 | 峰值 RSS/加速器内存、swap/内存压力、QwenPaw 非回归 | **blocked：未加载** |
| 声音权利 | 仅使用项目自有通用描述，记录“不模仿特定真人” | 描述已冻结，候选未生成 |

上表任一 `blocked`都不允许打开产品 capability。

## 4. 最小真实样本

使用 `metadata-baseline.json` 的两个项目自有描述，各生成 2 个不同固定 seed 的候选，总计 4 份：

| 描述 ID | T0-I 文本 case | 候选数 | 用途 |
| --- | --- | ---: | --- |
| `vg-neutral-young-adult-woman-zh` | `narration-neutral` | 2 | 检查通用年轻成年女声和候选间稳定性 |
| `vg-warm-middle-aged-woman-zh` | `anonymous-middle-aged` | 2 | 检查中年女声与前者的可区分性 |

文本只从 T0-I 授权台账按 hash 解析。VoiceGenerator 输出不进入 Git；证据只保存文本 ID、描述 ID、seed、revision/hash、计时、资源、WAV hash 和脱敏听检。

Nano 二次克隆至少包含：

- 同文本克隆：用于听辨 VoiceGenerator 直接样音与 Nano 克隆的身份保留；
- 留出文本克隆：使用同一参考声音读另一条 T0-I 文本，排除只记住原句的假保持；
- 独立句段：不使用 rolling prompt，与首版正式策略一致。

## 5. 必填测量

每个真实运行必须满足 `moss-tts-benchmark-result/1.0`，并另记录：

- 冷启动、模型导入、权重加载、首包、合成总耗时和 RTF；
- 子进程峰值 RSS、MPS allocated/driver memory（如适用）、系统内存压力与 swap 变化；
- 加载前/退出后 QwenPaw 健康和原生聊天非回归；
- 每个 WAV 的 SHA-256、样率、声道、时长、峰值、RMS、静音和削波；
- VoiceGenerator 进程退出后才能出现的 Nano 子进程 PID；
- 人工听检的漏字、重复、音色漂移、异常停顿、接缝、爆音/噪声和响度不一致。

相似度算法只能作为辅助；未冻结有授权的 speaker embedding 模型前，不为了一个分数自动下载第三模型。真实人工听检不可被 WAV 技术指标替代。

## 6. Go / Hide 裁决

`visible` 需要以下全部成立：

1. 两个模型阶段串行并能完全释放资源；
2. 本机至少一个 MPS/CPU 路径真实生成成功，不使用 CUDA 结果代替 M4 结果；
3. 实测内存压力可接受且不拖垮 QwenPaw；阶段 0 暂定的保守门禁是峰值时仍保留 4 GiB 安全余量，最终由 T0-GATE 冻结；
4. 四份候选都可解码，人工听检无漏字/重复/明显音色漂移；
5. 至少一个候选在同文本与留出文本 Nano 克隆中都通过；
6. 候选声音经作者显式锁定后才成为不可变参考版本。

任一项未完成就继续 `hide`，不把“官方支持文字描述”扩大为“本项目 M4 已可用”。回退路径为“用户自有/已授权上传录音或已锁定预设 + Nano”；这不阻塞核心多角色朗读。

## 7. 本轮实际记录

```text
VoiceGenerator 权重下载   0
Full codec 权重下载     0
Torch/Transformers 模型导入 0
VoiceGenerator 加载        0
候选样音生成               0
Nano 二次克隆              0
真人听检                    0
当前裁决                    hide
```
