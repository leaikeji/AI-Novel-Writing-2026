# TTS55 最终复核

状态：**最终 PASS，且已完成长期发布。默认旁白、人物卡自动专属音色和中文 24 槽通用音色包均已通过机器、真实模型、桌面浏览器、真实章节与作者听检门禁；长期 `18088` 的备份、`0040` 迁移、安装、重启、只读复验与隔离资源清理见[`TTS55-RELEASE`](./TTS55-RELEASE.md)。**

日期：2026-09-03（Asia/Shanghai）

## 1. 边界

- 施工分支：`main`，基线 `c241b90d8096acca6542bf551b2e2cc188cf2f8e`。
- 隔离验收阶段未迁移或替换长期 PawApp `127.0.0.1:18088`，也未写入真实用户小说／媒体；其后的正式发布仍只对长期真实小说执行只读复验。
- 真实写入只发生在隔离 PostgreSQL、隔离媒体目录、隔离 Sidecar 和 `127.0.0.1:18192` 的临时 PawApp。
- 候选随后由用户明确授权提交、推送和长期部署；源码提交为 `a2b1e90`，发布事实以[`TTS55-RELEASE`](./TTS55-RELEASE.md)为准。

## 2. 本轮收口修复

1. QwenPaw 2.1 热卸载会以关键字传入 `plugin_id`。卸载钩子现兼容该公开参数，重复安装时可以先完整停止旧朗读运行时。
2. 过期的分段任务在同一 Edition 尚无可播放段、其他兄弟任务仍待处理时，不再错误地提前发布 Manifest；全体终态或已有可播放段时才发布。
3. VoiceGenerator 与通用音色生成的参考音频在 Nano 克隆阶段统一使用 `sample_mode=full`；不再把高级解码参数错误地送入 `fixed` 模式。
4. 无正式人物卡的匿名／群体说话人已接入通用音色池；人物卡角色继续优先使用专属音色，旁白固定使用 Junhao。
5. 临时诊断写入已移除；保留的日志仅记录可恢复后台循环的异常，不包含正文、密钥或音频内容。

## 3. 自动化与迁移

| 门禁 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest` | `3754 passed, 191 skipped` |
| `pnpm test` | `142 files / 1209 tests passed` |
| `pnpm typecheck` | PASS |
| `pnpm build` | PASS，183 modules transformed |
| 插件打包 | PASS |
| manifest／Skill／QwenPaw 契约 | `136 passed` |
| 隔离 PostgreSQL 0040 往返与 Plan 55 专项 | `19 passed` |
| 失败／漂移／幂等／互斥专项 | `10 passed` |
| `docker compose config --quiet` | PASS |
| `git diff --check` | PASS |

隔离 PostgreSQL 使用一次性容器和专用数据库 `ai_novel_world_2026_tts_test`；验证后已移除该临时容器。第一次把历史迁移测试与要求 head 的业务测试错误地放在同一数据库顺序执行，历史测试按设计把数据库留在旧 revision，产生的是验收编排错误而非产品失败；改为独立 0040 往返后，规定门禁全部通过。

## 4. 真实模型闭环

隔离小说：`雾港无声`（`9b83557c-87d6-476a-b4bb-71c8d7c105ee`）。

### 默认旁白

- 新书设置中的 `preset_key=onnx.Junhao`。
- Voice Version 为 `locked`，激活依据为 `explicit_official_preset_selection`。
- 普通建书与向导建书的同事务初始化、失败回滚和作者后续选择不被回正均由全量回归覆盖。

裁决：`TTS55-DEFAULT-FINAL=PASS`。

### 人物卡自动专属音色

- 两位主角：沈砚、方若岚。
- 四位配角：罗岑、乔榆、杜文山、梁策。
- 六个 VoiceGenerator 命令均为 `ready_applied`，进度 `6/6`。
- 六个绑定均为 `dedicated + character_one_click_generation + machine_validated + accepted + locked`。
- 每个目标均保存 VoiceGenerator requested/actual model 成功证据及 Nano requested/actual model 成功证据。
- 六次真实 VoiceGenerator 运行证据全部为 success、`stage_pid_overlap=false`，并均在 60 秒内恢复；没有 VoiceGenerator 与 Nano 模型进程重叠。
- 模型失败保留原官方音色、人物卡／正文摘要漂移、绑定 CAS 漂移、响应丢失重放和失败重试的零破坏语义均由专项回归覆盖。

裁决：`TTS55-CHARACTER-FINAL=PASS`。

### 中文通用人物音色包

- active pack：version 9，`a869104f-903e-548a-a2be-ba34c6283dbe`，`zh-CN`，`24/24`。
- 24 个槽位均有独立 Voice Version，全部 `rights_approved=true`、`quality_approved=true`。
- 首轮作者拒绝 `female_child_bright`、`neutral_young`、`crowd_male` 后，系统严格逐槽串行创建 v6、v7、v8；每一轮均只重生成被拒绝槽，其余 23 槽复用已验证版本。
- v8 中三个替代 Voice Version 分别为 `b8ff7a3b-c15f-5e55-9bbc-2fdac69638d4`、`96d1afce-d606-5651-b700-85ebe084757c`、`a021d455-cc7e-529c-845d-38d7ce45da01`，均保存 VoiceGenerator 与 Nano requested/actual model success 证据。
- 作者复听后接受 v8 的 `female_child_bright` 与 `neutral_young`，拒绝 `crowd_male`：实际听感只有一个人且说话缓慢。复核确认模型链一次只能生成和使用一条声线；旧描述中的“多人共同回应时的整体感”错误暗示了多人合声能力，也容易诱发刻意拖腔。
- `crowd_male` v9 已改成明确的“未具名男性群体简短对白所共用的成年男性单人声线”，要求语速偏快、句尾干净、不拖腔、不模拟多人合声；seed 从 `550024` 更换为 `551024`。新 Voice Version 为 `a95b8c2a-cc1e-59df-bcf1-6bd95ded7bc1`，VoiceGenerator 与 Nano 验证均成功。
- v9 新试听为 48 kHz、双声道、16-bit WAV，时长 `3840 ms`、SHA-256 `76a929d18dc31a3e13cceb76937463eaf072e3cdafb27532586e0bbfec5a513d`；较 v8 的 `4960 ms` 缩短约 23%。
- 通用音色包界面不再显示易误解的“群体·男性／女性”，而显示“未具名男性／女性对白（单声线）”；隔离 PawApp 真实 DOM 已确认新名称可见且旧名称不存在。
- v5、v6、v7、v8 均已 `retired_for_new_use`，旧声音资产与历史 Edition 未删除或改写。
- 真实章节《潮痕证词》：document `c44777ec-efe4-4e79-8097-ba0ee6da1325`，request `68f26262-7cad-4fb9-b370-26491044b8f9`，Edition `5ea5346a-7d4e-45a2-9957-29da7eb54a8b`。
- Edition 为 `ready`，16/16 段 ready，11 个后台任务均一次成功，实际使用旁白加 6 个不同通用 Voice Version。
- 实际槽位为 `male_child_bright`、`female_young_bright`、`male_middle_warm`、`female_elderly_kind`、`neutral_young`、`crowd_male`；旁白全部为 Junhao。
- 渲染证据为 5 次 Nano 直接合成和 6 次 VoiceGenerator 参考音频经 Nano 克隆合成，全部为 success。
- 作者拒绝后的新智能朗读 request 为 `5e6f5518-f9d5-4aaa-badd-577c9f0edfd8`，新 Edition 为 `111d7bdd-0c75-4005-8a32-93e3248a7613`；其状态为 `ready`、16/16，小说级投影已从 retired v5 原子切换到 active v8。
- 作者接受 v9 后，最终智能朗读准备命令为 `47e05aee-5352-4c95-adf1-6a237c5b7b6f`，request 为 `dd47c6fb-02cb-4753-bab6-50fc23c49bc0`，Edition 为 `73c1d280-e909-4ff2-b4b0-86d447bf3a70`；其状态为 `ready`、16/16。小说当前完整投影指向 active v9，群体段实际引用 `crowd_male` v9 Voice Version `a95b8c2a-cc1e-59df-bcf1-6bd95ded7bc1`。
- 原 v5 Edition `5ea5346a-7d4e-45a2-9957-29da7eb54a8b` 仍为 `ready`、16/16，证明拒绝和替代包不会改写历史朗读。

机器裁决：PASS。作者听检：PASS。产品裁决：`TTS55-POOL-FINAL=PASS`。

## 5. 桌面浏览器验收

只按用户要求覆盖桌面端：

- `1920×1080`：章节正文、播放器、目录与原生助手无重叠；播放器对齐中间写作区。
- `2560×1440`：同样保持三栏边界，播放器不侵入助手。
- 人物配音页显示 6/6 专属声音且无待配置人物。
- 官方音色页显示 `CN 欢迎关注模思智能` 为当前作品旁白。
- 私人音色页的中文通用角色音色区默认折叠，展开后显示 `24/24`。
- 两个桌面尺寸下页面均无横向溢出；浏览器控制台无 warning/error。

证据：

- [`1920×1080 章节播放器`](./TTS55-browser-1920x1080.png)
- [`2560×1440 章节播放器`](./TTS55-browser-2560x1440.png)
- [`1920×1080 人物配音`](./TTS55-UI-1920x1080-character-roster.jpg)
- [`2560×1440 默认旁白`](./TTS55-UI-2560x1440-default-narrator.jpg)
- [`2560×1440 通用音色折叠区`](./TTS55-UI-2560x1440-private-generic-collapsed.jpg)

## 6. 作者听检结论

作者已确认此前的 2、3、4，以及重生成后的 `female_child_bright`、`neutral_young`；2026-09-03 最终确认 `06-crowd-male.wav` 试听通过。

最终文件为 48 kHz、双声道、16-bit WAV，时长 `3840 ms`，SHA-256 为 `76a929d18dc31a3e13cceb76937463eaf072e3cdafb27532586e0bbfec5a513d`。被拒绝的 v8 文件保留在 `/tmp/tts55-listening/rejected-before-v9/`，更早首轮文件保留在 `/tmp/tts55-listening/rejected-before-v8/`，均未销毁。

最终裁决：`TTS55-DEFAULT-FINAL=PASS`、`TTS55-CHARACTER-FINAL=PASS`、`TTS55-POOL-FINAL=PASS`；本轮全局默认与自动音色闭环完成。
