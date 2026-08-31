# VG40 MOSS-VoiceGenerator 最终机器与产品闭环报告

日期：2026-08-31

当前裁决：`VG16-FINAL=HOLD_AUTHOR_LISTENING`

## 1. 发布与模型身份

- 源码候选分支：`codex/vg40-implementation`；当前基线提交 `940fdb17cf009745bb98ed374b20354d588ff53b`，本轮改动尚未提交。
- 长期数据库：`20260830_0035 (head)`。
- 前端 bundle SHA-256：`887304e528a96317913c61ee6da48e9cb779a2ca07a7d9479d29d7e962e54cbd`。
- 模型来源清单 SHA-256：`5ce7e9270c136bb41dd0ac46020520e2bedab19c52c56722f630a2f351085a1d`。
- VoiceGenerator：`OpenMOSS-Team/MOSS-VoiceGenerator@97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4`。
- Audio Tokenizer：`OpenMOSS-Team/MOSS-Audio-Tokenizer@3cd226ba2947efa357ef453bcad111b6eafba782`。
- 拓扑：Apple MPS/BF16、VoiceGenerator 与 codec 分阶段一次性进程、Nano 串行二次验证；未量化；Nano 与 VoiceGenerator 驻留重叠为 0。

## 2. 16 GiB 真实运行证据

- T5 三个 seed `104729`、`130363`、`155921` 均完成冷运行，输出 WAV hash 互不相同；生成阶段分别约 `9.176s`、`10.171s`、`9.365s`。
- 三次生成最低系统余量约 `3.117–3.129 GiB`，codec 阶段最低约 `3.368–3.705 GiB`；无持续 critical pressure，退出后 60 秒回收通过。
- 正式沈砚任务最低可用内存 `1,889,026,048` bytes，swap delta `4,172,346,819` bytes，最大 page-out `26/s`，critical pressure 为 0；两个重阶段无重叠并在 60 秒内回收。
- 取消与注入 `SIGKILL` 均无 Voice Version、绑定或临时资产泄漏；宿主退出后 Nano 才获准运行。
- 此结论只适用于当前用户明确接受低余量风险的这台 M4／16 GiB 主机及固定拓扑，不外推为通用 16 GiB 安全认证。

## 3. 正式人物一键生成

- command：`b32afe0f-9bb0-4bc4-aead-caeeb56db3d6`，状态 `ready_applied`，进度 `6/6`。
- VoiceDesignDraft：`3f41cb41-a0e7-43c3-a2e0-d69685822451`。
- VoiceGenerator 参考资产：`9ec9ce22-783e-578f-b524-ca4a1b724e79`，`1,413,164` bytes，`7.36s`。
- Nano 验证资产：`a0eb7a6e-cb84-576d-bfe6-c0bf78120e51`，`1,029,164` bytes，`5.36s`。
- generator ModelRun：`af6dbe45-84b6-5cfd-9bf0-bd2a30a2ff1f`；Nano ModelRun：`63bf6d7c-7ee9-5aeb-bdb6-e1cbec356c59`。
- Profile：`4f62f756-5244-530e-b8c5-f875a3b74844`；generated Version：`653ae852-ebdc-55d0-b582-7cf52dfa9f8f`。
- 绑定 CAS 未漂移，人物绑定版本由 1 更新为 2；完整链路耗时约 257 秒，满足首次任务 `≤300s` 门禁。

## 4. 正式小说与 Edition

《潮汐盲区》在进入 TTS 前已冻结两卷四章、两位主角和五位配角；TTS 施工没有改写标题、卷章、正文或人物卡。

| 章节 | 当前 Edition | ready |
| --- | --- | ---: |
| 空播室里的来电 | `b0ca6d9a-9c44-4994-9ec5-1c982b7f5201` | `117/117` |
| 第四条声轨 | `48927bc0-e7eb-4947-9be2-301bca37afd2` | `100/100` |
| 退潮名单 | `604e6ae5-ea2e-452b-b624-a5ac07097226` | `144/144` |
| 零点之前 | `0475f56a-86ed-4c88-8fb3-e5bf072c16ee` | `141/141` |

合计 `502/502` 句段 ready。四章 current pointer 均为 version 2；目标人物使用 generated Version，旁白与其他人物继续使用绑定的官方 Version。旧的部分 Edition 和 33 次历史失败尝试保留为审计历史，不计入当前 Edition 失败，也不删除。

## 5. 浏览器、删除与回归

- 人物卡显示“专属音色已生成并用于当前人物”；统一私人音色档案与删除影响投影可见，正式 generated 音色未被物理删除。
- 章节播放器真实完成播放、暂停、前后句、进度、倍速、当前说话人与冻结 Edition 检查；四视口通过，控制台无 warning/error。详见 `VG40-BROWSER-QA.md`。
- 后端全量：`3369 passed, 150 skipped`。
- 前端全量：`113 files / 983 tests passed`；typecheck、production build 通过。
- manifest、Skill、QwenPaw 契约：`127 passed`；插件打包通过；Compose 以不含真实密钥的占位变量完成结构解析；`git diff --check` 通过。

## 6. 最终 Gate

| Gate | 裁决 |
| --- | --- |
| `VG16-FEASIBILITY` | PASS |
| `VG16-SAFE` | PASS_LOCAL_RISK_ACCEPTED |
| `VG16-QUALITY` | MACHINE_PASS_AUTHOR_LISTEN_HOLD |
| `VG16-PERF` | PASS |
| `VG16-PRODUCT` | PASS |
| `VG16-FINAL` | HOLD_AUTHOR_LISTENING |

唯一未完成项是作者主观听检。作者在页面播放沈砚的两句以上对白并确认自然度、可懂度、人物一致性和跨句稳定性后，若接受，可把 `VG16-QUALITY` 与 `VG16-FINAL` 更新为 PASS；若不接受，应重新生成候选或恢复官方音色，不修改小说正文迎合音色。

## 7. 回退与残余风险

- 异常时先撤销 `voice_generator` capability，停止新命令；保留 `0035`、已生成 Version、绑定和媒体审计，不降 schema。
- 16 GiB 正式任务曾出现约 3.89 GiB swap 增量，虽然本次无 critical pressure 或死机，后续仍只允许一次一个重任务，并继续保持 Nano／VoiceGenerator 串行。
- 两个早期失败 publication 留下的无数据库引用媒体文件和历史失败记录尚未清理；它们不参与当前 Edition。后续只能经内容身份核对和现有 GC/对账路径清理，不能手工批量删除。
