# T0-C Reference Clone 无模型技术准备

状态：**本页的无模型准备阶段已完成：3/5/8/12 秒 isolated-test-only 技术参考资产在仓库外准备并验证；当时没有取得 `LOCK-NANO`、没有加载模型、没有接线尚未冻结的 T0-B reference API、没有运行 4-case 克隆。后续 T0-B 已冻结共享协议并在 Linux 真容器完成四档技术 smoke；本页不反向改写历史执行事实。**

## 来源与边界

- 唯一来源是 T0-C 已完成真实 run 的 `long-sentence/segment-001.wav`，输出 hash `1c1cce3081f4fbebe61e3267e0173f83e3b6ced038309c343e8912be804b7c71`，时长 20.08 秒。
- 对应 `txt-long` 是项目 T0-I 新编的自有测试语料，只限仓库开发与验收使用；不是外部小说正文或第三方录音。
- 技术参考只证明 reference-input 的长度、格式、hash 与离线管线可复核。它不是可发布音色资产，不授予产品使用、分发、角色声音或第三方权利。
- 四个文件只位于外部受控媒体目录 `<controlled-media-root>/T0-C-reference-clone-prep.Y7c1Yh/`；Git 证据只有 hash/规格/命令，没有音频和私人绝对路径。
- 不修改冻结 fixture 中四个 `placeholder_only/not_supplied` profile，不把这些技术候选冒充已经批准的产品参考音频。

## 固定裁切

使用 T0-A 固定的 FFmpeg 9.0.1 LGPL 窄构建，binary SHA-256：

`f39e5777dc535a6bcf9301a0c1766e6008b259893083d4effbb226e01532bc28`

命令模板：

```bash
<ffmpeg> -nostdin -hide_banner -loglevel error \
  -i <source-wav> -map 0:a:0 \
  -af atrim=end_sample=<48000*seconds> \
  -map_metadata -1 -c:a pcm_s16le -ar 48000 -ac 2 \
  <external-output-wav>
```

这里的“无损裁切”指：只解码/重封装 16-bit PCM，不做有损编码；每个输出的 PCM samples 与源文件前 N frames 逐样本完全一致。另在 `/tmp` 重复构建一次，4/4 文件均 `cmp` byte-exact。

## 资产结果

| 时长 | frames | WAV SHA-256 | PCM SHA-256 |
| ---: | ---: | --- | --- |
| 3.0 秒 | 144,000 | `e6bdfb47d570399960b9e4e23bddc2ba57bebc72972723e10c6ef5085709b73e` | `015cb6b6f4aacd01c47a50ef741c8af7609b5f0d9b53b7e10d55df185bac32d9` |
| 5.0 秒 | 240,000 | `8003035e04444005269edfe6b21e5f79c973f09956a0b54f5a135c54b5e001fd` | `93dcfdf7a364daffb4e7772666c59b267f44b38e94f42fb2deb774b392ee15b0` |
| 8.0 秒 | 384,000 | `f9ce35ad1be674b911ea975cef4d6b5b105f79d697ec54e2c0727f341a9d08ab` | `aa4a5ddb87b1580adea08686da61f64b1e95ff8d1c7158d73b20af3bbff93622` |
| 12.0 秒 | 576,000 | `d7bf1020633fcd96811281842ebcabcd4d0e09e994387abd26a03f7a6605f9dc` | `d53d3978b558a68e736a94854c58a5085c3372aec4486d996b594b1575e0abc8` |

全部为 48 kHz、双声道、16-bit PCM WAV，实际时长与目标精确相等。完整机器可读记录见 `asset-manifest.json`，SHA-256 `5c983437492c4a58f5160e29bfc6a669697ce6b9c513caef648c9bfb8b62297c`。

## 驱动负向门禁

`validate_reference_audio()` 现明确要求：

- 仓库外现存普通文件，不接受仓库内路径或 symlink；
- 显式 lowercase SHA-256 且逐文件重算一致；
- 48 kHz、双声道、16-bit PCM WAV；
- 实际时长在显式 tolerance 内；
- `--reference-audio` 与 `--reference-sha256` profile 集合完全一致，未知 profile 拒绝；
- 命令证据中的 reference 绝对路径继续脱敏。

Python 3.11 当前 10/10 单测通过；新增 valid reference 正路径以及 hash、时长、格式、symlink、仓库路径、CLI 参数配对与绝对路径脱敏负向测试。假 worker 仍不会接收 reference 参数；当前 reference case 只能明确 `managed_worker_reference_audio_unsupported/blocked`。

## 等待条件

该准备阶段原定的后续门禁已经由 T0-B 的唯一共享 Sidecar 协议与 Linux 真容器四档技术 smoke完成；无需再复制一套 T0-C 模型调用。资产仍只有 isolated-test-only 技术用途，产品权利与人工听感未通过，reference cloning 继续隐藏/blocked。
