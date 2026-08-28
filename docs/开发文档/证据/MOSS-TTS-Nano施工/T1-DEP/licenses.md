# T1-DEP 许可证与再分发边界

状态：**依赖层技术锁已完成；不是最终法务或 registry 发布批准。**

生产 build context 内的 `NOTICE`、`THIRD_PARTY_NOTICES.md`、三组件 29 项逐文件 allowlist 和镜像内
Python distribution metadata 记录当前依赖归属。模型、源码、私人参考录音、小说媒体和生成音频
均未进入镜像；allowlist 只批准受控下载与逐字节核验，不扩大任何人声音频或输出人格权。

| 对象 | 当前固定值 | T1-DEP 结论 |
| --- | --- | --- |
| MOSS-TTS-Nano 源码 | `cc7bdf19…f6be` | Apache-2.0 元数据；只通过后续只读卷提供，当前镜像不复制源码 |
| Nano 100M ONNX | `f52645cb…e58` | 模型仓库元数据为 Apache-2.0；权重不在镜像，正式再分发权利仍需复核 |
| Audio Tokenizer ONNX | `ceff0d07…1e1ae` | 同上；权重不在镜像 |
| FFmpeg | 9.0.1，source SHA `cf38e0e2…7f635` | 静态窄 LGPL 构建；GPL/version3/nonfree/network/autodetect 均关闭，二进制与源码内许可证 hash 已验证 |
| Python 闭包 | `requirements.lock` SHA `196885c7…0ac3` | exact versions + wheel hashes；运行时安装元数据保留 |
| GNU OpenMP | Debian `20260825T000000Z` snapshot | 只复制固定 `libgomp.so.1`，实际 SHA `9d8c6a61…0d30` |

仍未完成且不能被 T1-DEP 技术通过覆盖：FFmpeg 发布源码 PGP 链、最终许可证归档、registry
再分发审查、模型权重对外分发权利、任何人声音色/公众人物/私人参考录音权利与人工听感。

> **现行范围说明（2026-08-27）：** 上述未完成项是商业发布／registry／模型与音频再分发，以及外部／用户参考录音的风险记录；不得据此阻断固定 ONNX manifest 18 项 `official_preset` 的个人本地展示、试听、绑定、合成和播放，也不得建立公众人物预设排除名单。
