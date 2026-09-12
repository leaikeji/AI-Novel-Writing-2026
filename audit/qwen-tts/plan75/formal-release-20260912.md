# 计划 75 正式发布与验收证据

状态：**PASS（正式 `18088`）**

日期：2026-09-12（Asia/Shanghai）

## 发布对象

- QwenPaw：2.2.0，原长期容器 `ai-novel-2026-qwenpaw-lab`。
- 候选 tree SHA：`8e22b70d4ea050b42afdcaaa1d799099da7f09696b074a260423b008d776ee55`。
- 正式数据库：`ai_novel_world_2026`，精确升级 `20260911_0053 -> 20260912_0054`。
- 本地模型：`mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit`，revision `41d3337e8b7f2843a75841595fc14e4b9a7a4b96`。

## 发布前备份与恢复演练

宿主恢复目录：`/private/tmp/ai-novel-world-2026-plan75-20260912-142551-before`（0700）；QwenPaw 专用备份卷副本：`/app/working.backups/plan75-20260912-142551-before`。

| 文件 | 字节 | SHA-256 |
| --- | ---: | --- |
| `database.dump` | 50,856,112 | `260de3f8e1d8629ce3203f6291309b5e613d26805dca06dab024c5f224e34c5d` |
| `installed-plugin-before.tar.gz` | 4,647,962 | `7df1ade93352924efb32a0943244532d279e15171f7680043bc4de1bb3f06b2a` |
| `candidate.tar.gz` | 2,234,151 | `25178e396f128b6732181e0243d729867cc219cbfc6df40e94089a4dad5dea5a` |
| `skills-before.json` | 389 | `db67f68d79f23837a1bf9060e6274d3453fb3807786867c8489c46d3ae0bfde6` |

- `pg_restore --list` 通过。
- dump 已恢复到独立临时数据库并核对 head=`0053`、旧官方声音版本=4；随后精确删除临时数据库。
- 失败恢复路径：停止长期 QwenPaw，以本批 dump 恢复数据库、以旧安装树恢复 PawApp、再恢复 `skills-before.json`；不删除 PostgreSQL、QwenPaw、模型或媒体卷。

## 数据库与公开安装

- 发布前活动后台任务：0。
- 0053 bootstrap／61 表角色、owner、ACL validator：PASS。
- schema-owner 精确升级到 0054：PASS。
- 0054 bootstrap／61 表角色、owner、ACL validator：PASS。
- QwenPaw 公开 `plugin install --force`：PASS；未覆盖或修改 QwenPaw 核心代码。
- 启动后健康、database、narration production backend、worker 均为 ready；Agent 模型仍为 `bigmodel/glm-5.3-flash`，11 个小说 Skill 和 5 个小说工具保持可用。

## 正式 9 音色 HTTP 试听

请求只提交 `preset_id + language`；固定试听文本在服务端选择。响应全部为 `audio/wav`、`Cache-Control: no-store`、Provider=`local_qwen3_tts`，模型及 revision 与本页发布对象一致；音频只在内存校验，没有落库或进入 Git。

| preset | speaker | 字节 | 时长 | SHA-256 |
| --- | --- | ---: | ---: | --- |
| `qwen.WarmFemale` | `Serena` | 314924 | 6.560s | `ac8e6292395e8bc7e4630dd26035a7e4c4eb84e58d9ef8e7f40b9d2e40d53b6b` |
| `qwen.Vivian` | `Vivian` | 288044 | 6.000s | `0259438c8a35fcadb7044cab518acabc5915247e68f8ead10f5304714df47d53` |
| `qwen.UncleFu` | `Uncle_Fu` | 453164 | 9.440s | `424b9b8e8fa6ba4db56660ff31be8249f90d384338d2dde1c9f4274cd2dcb79d` |
| `qwen.Dylan` | `Dylan` | 265004 | 5.520s | `7a38a918d74daf434f36befda285c3db3add5d617f37340211da909464141cc3` |
| `qwen.Eric` | `Eric` | 364844 | 7.600s | `b2bb69a6c571f5bedce81d4559d43d6265540b5b0dde00588c7b19fc6802624e` |
| `qwen.ClearMale` | `Aiden` | 295724 | 6.160s | `5db9cc6a3e0dab3e193772e23371236a4373bb332c9a92128d063c0ef518a248` |
| `qwen.Ryan` | `Ryan` | 326444 | 6.800s | `349238fbf0894b0227785a25d4ae6d4e5515b329627849949ce367ff50add1a7` |
| `qwen.OnoAnna` | `Ono_Anna` | 291884 | 6.080s | `b55385c357f141e3c70d6281965f27a64cde36311e6158087867d5f63ae1ab63` |
| `qwen.Sohee` | `Sohee` | 272684 | 5.680s | `6a02b4c2a61cc0bb00e468f238f7e1bb7a8f073bbcdc0d21ea7f4644ff4c9ebf` |

## 桌面页面验收

- “官方音色库”显示 9 项；中文 6、English 1、日本語 1、한국어 1。
- 逐个语言筛选可见 Ryan、Ono_Anna、Sohee；中文页可见 Serena、Vivian、Uncle_Fu、Dylan、Eric、Aiden。
- 页面点击“本地试听 Sohee｜温暖女声”后先显示局部加载，随后显示“本地试听已开始”；未刷新工作台，也未改变当前旁白选择。
- 浏览器没有新增 error；只观察到 QwenPaw 宿主已有的 `AppCenter`／`Chat` moduleRegistry warning。

## 数据不变性说明

把发布前 dump 再次恢复到独立临时库，与正式库使用同一规范 JSON 聚合算法逐表比较：`media_assets`、`narration_editions`、`narration_edition_segments`、`narration_render_assets`、`narration_segment_renders`、`novel_narration_settings`、`voice_profile_versions` 数量与摘要完全一致，旧两官方 preset 版本仍为 4。

`character_voice_bindings` 从 12 增至 13。新增记录更新时间为 `2026-09-12T06:28:42.898355Z`（Asia/Shanghai 14:28:42），引用既有 `qwen.WarmFemale`／Serena 声音版本；它发生在备份后、长期容器停服及 0054 迁移／插件安装前的在线业务窗口，不是试听路由或迁移写入。该正常业务数据已保留，未为追求哈希相等而删除。

## 结论与保留项

正式发布结论为 PASS：catalog v2／9 音色、真实本地试听、桌面入口、数据库 0054、Skill 保态和旧朗读资产均已核验。真实阿里云凭据 smoke 仍属于计划 61，不在本次无云端调用范围内。

隔离生命周期脚本仍有 Docker Desktop `start-postgres` 不返回的失败证据，见同目录 `lifecycle*.json`。正式发布成功不把该隔离失败改写为通过。
