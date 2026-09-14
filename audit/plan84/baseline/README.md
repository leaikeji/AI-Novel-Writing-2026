# 计划84正式环境冻结基线

记录时间：2026-09-14 21:52 CST

状态：`PASS`（允许进入 `P84-CENTER`；尚未部署候选）

## 环境

- 正式地址：`http://127.0.0.1:18088`
- QwenPaw：2.2.1
- 正式容器：`ai-novel-2026-qwenpaw-lab`，健康状态 `healthy`
- 正式运行镜像：`ai-novel-2026-qwenpaw-runtime:2.2.1-mvp0`
- Compose 记录镜像摘要：`sha256:5591aee95c9ce53fb4e19cc64e8baf5ef02ab7cc74130f141590f39dfa7a7d99`
- PawApp：`ai-novel-world-2026` 0.4.0，`enabled=true`、`loaded=true`
- 已安装插件树确定性哈希：`9bcf3348c00059e5ed95cb71a958495a0e659f9257272a4ed08affe942bc50ee`
- 数据库迁移 head：`20260913_0056`

## Agent公开配置

- Agent：`ai-novel-writer`，运行中
- 生效模型：`bigmodel/glm-5.3-flash`
- prompt 文件：`AGENTS.md`、`SOUL.md`、`PROFILE.md`、`AI_NOVEL_WORLD.md`
- Skill：共12项且12项启用；名称与计划83冻结基线一致。
- 工具：公开接口共35项，33项启用；`append_file`与`delegate_external_agent`仍为停用，小说工具选择未漂移。

未读取、输出或归档任何密钥。

## 正式数据只读基线

- 公开作品列表：5本。
- 数据库作品根行：6行；该值包含当前公开列表未返回的生命周期记录，因此发布前后分别比较公开口径与数据库口径，不混用。
- 建书草稿：6份。
- 私有库现有词汇表：2份。

私有库内容版本以版本历史中 `current=true` 为准：

| 资产 | asset id | 根CAS version | 当前内容版本 | 当前版本id |
| --- | --- | ---: | ---: | --- |
| 灾后设施抢修词 | `9ab0735e-c7a7-4094-8efe-132104f7b506` | 4 | 4 | `dbad10e0-f721-4349-a911-a33c0fce92ea` |
| 雾港时间异常术语表（三章验收） | `22a4ff46-4bc9-4af0-92ef-b60517b4b1ef` | 2 | 2 | `4be0f3b5-2e33-4811-9a76-17d086d84e92` |

现行摘要响应没有 `content_version_number`，值为 `null`；这正是本计划要补齐的响应合同。当前两份词汇表的根CAS与内容版本碰巧相等，自动化必须另造“二者故意不相等”的工作区临时库反例，不能把正式数据巧合当成实现正确证据。

## 当前URL行为

- 从官方 PawApp 入口 `/apps/ai-novel-world-2026` 打开后能显示创作中心。
- 宿主分配会话后，最终地址变为 `/chat/b9c0bbb4-ff55-4ad5-bbae-a092028b1302`，没有 `novel_center=1`。
- 该基线复现 F84-01；普通不带参数的 `/chat/{sessionId}`仍显示原生聊天。
- 本次浏览器自然视口为 `2552×1251`、DPR 2，页面无顶层横向溢出。计划规定的三种桌面矩阵留到候选发布后按精确尺寸复验。

## 唯一建书草稿冻结

正式数据中最近活动且未完成、更新时间与本轮网页检查一致的草稿 key 为 `novel-12c6bb79-bf72-4416-a1e0-b1ff9209539d`。公开浏览器控制面不允许读取 `localStorage`，因此这里把该草稿登记为本计划唯一草稿候选，而不伪称已经直接读到浏览器存储值；正式Escape复验打开向导后必须先核对实际返回ID，若不同立即停止。按计划只调用一次公开 `POST /api/ai-novel-world-2026/creation-drafts`，返回：

- id：`c150ebf2-a5a9-400a-ae33-9b96c6f59e21`
- state：`draft`
- version：3
- step：1
- completed_novel_id：`null`

调用前后公开作品数均为5，数据库作品根行均为6；草稿仍为同一ID、同一版本，未创建第二份草稿、未完成作品。本计划后续正式Escape验收只允许复用该草稿，并只允许非忙碌关闭触发一次预期保存。

## 冻结停止条件

以下任一发生即停止安装或验收：URL循环或普通聊天被接管；草稿意外完成或出现第二份计划84草稿；作品、私有库版本、Agent模型、Skill、工具或prompt清单漂移；容器／PawApp健康异常；修复需要修改QwenPaw上游核心。
