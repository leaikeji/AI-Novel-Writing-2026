# 计划 65：创作中心整书删除修复与测试小说清理证据

日期：2026-09-10。状态：已完成并 PASS；长期安装、真实页面删除、媒体销毁和最终残留审计均已完成。

## 根因与修复

旧 `DELETE /novels/{id}` 仅删除 ORM 小说对象。含朗读数据的《雾宅来信》同时存在不可变触发器、直接 `RESTRICT` 外键以及后台 attempt／manual-retry 双向引用，数据库按设计拒绝旧路径。新路径使用小说 UUID＋CAS、无活动任务门禁、事务内精确冻结、脱敏授权审计和子表优先清理；普通事务不绕过触发器或外键。两条本已声明为 DEFERRABLE 的循环外键从立即 `RESTRICT` 改为提交期 `NO ACTION`，提交时引用完整性仍受 PostgreSQL 强制。

数据库提交后才删除媒体，并重新核对相对路径、SHA-256、大小、设备和 inode；身份变化时停止物理删除并保存 `media_cleanup_failed`。页面成功后按服务端返回的文档 ID 清理当前浏览器 IndexedDB 恢复稿，失败只给出残留提示，不把已完成的服务端删除误报为失败。

## 冻结清单

删除目标：

- 《雨港来信》`af44b1e0-9a3d-459a-b915-a848c5ef8fc1`，version 1，1 文档／3 revision，0 媒体；
- 《裂隙追凶》`d8c51572-4c2d-4c72-8db9-4565695bf038`，version 2，1 文档／2 revision，0 媒体；
- 《雾宅来信》`d2aa0df8-43e4-4128-b63a-159a0a93ab5f`，version 2，2 文档／8 revision，206 媒体、28,694,526 bytes。

三本均为 0 个活动后台任务。保留目标为《刑侦1988:消失的档案》version 2、《潮汐盲区》version 4、《超能梦境》version 2；操作前共 6 本。

## 已完成验证

| 检查 | 结果 |
| --- | --- |
| 生产 dump 的隔离副本 `0050 → 0051` | PASS |
| 隔离《雾宅来信》完整数据库闭包 | PASS；206 媒体、169 jobs、483 attempts、483 model runs 对应数据库闭包可提交 |
| 隔离目标 UUID 扫描 | 业务表 UUID／文本／JSONB 列零残留；仅脱敏删除审计保留 |
| 隔离完整服务调用 | PASS；《裂隙追凶》删除并返回文档恢复稿清理 ID |
| `.venv/bin/python -m pytest` | 2689 passed、253 skipped、3 warnings |
| `pnpm exec vitest run` | 146 files、1270 tests passed |
| `pnpm typecheck` | PASS |
| `pnpm build` | PASS；187 modules transformed |
| `.venv/bin/python scripts/package_plugin.py` | PASS；后续维护链改动后须重新打包 |
| 数据库角色定向测试 | PASS；16 passed、5 conditional skips |
| 删除前数据库备份 | `database.dump`，16,880,984 bytes，mode 0600，SHA-256 `346ec557836ed5d92844c0a13d992cabe9cf6d844b7941ed5623a6ae81a5071a`；`pg_restore --list` PASS |
| 删除前媒体备份 | `media.tar.gz`，239,182,433 bytes，mode 0600，SHA-256 `2381d51582e6993c5653b2afb160795dd4d6d18990b1f3a7bc74a3c76be87766`；归档目录检查 PASS |
| 长期 schema-owner 升级 | `20260909_0050 → 20260910_0051` PASS；60 张保护表、110 relations、216 routines、owner／ACL／授权门禁 PASS |
| 长期插件安装 | 候选／安装树 SHA-256 `6b271b35fdda8f03639550771354ac56929fc5fd61d87919f0e4336edd821b3c`；健康接口 `ready`，QwenPaw 2.2.0 宿主容器 ID 不变 |
| 真实页面手动删除 | PASS；作者动作时再次确认，依次删除《雾宅来信》《裂隙追凶》《雨港来信》，6 本递减为 3 本 |
| 删除审计 | 3/3 `completed`；数据库删除与媒体删除时间均存在，failure code 为空 |
| 媒体残留 | 《雾宅来信》206/206 个冻结路径均不存在；另外两本清单为空 |
| 全业务表残留扫描 | UUID／文本／JSON／JSONB 动态扫描 `TOTAL_RESIDUE_ROWS=0`；只保留脱敏 `novel_deletion_audits` |
| 浏览器清理结果 | 页面未出现媒体待清理或恢复稿清理失败提示；三个测试书名在创作中心均为 0 个可见匹配 |
| 三本保留作品 | API 仅返回三本；版本、文档、revision、媒体、jobs、角色计数与删除前隔离快照完全一致 |

条件跳过不记为通过。三个 warning 为现有 Starlette/httpx 与 HTTP 422 弃用提示。本轮没有调用模型、读取正文、删除数据卷、提交或推送。

## 恢复

删除前恢复点位于仓库外 `/Users/liujia/Documents/AI小说世界2026-backups/plan65-novel-delete-20260910-174133-before`。如需恢复，必须先停止写入，再把同批 `database.dump` 和 `media.tar.gz` 作为一个一致恢复单元执行；`0051` 为前向迁移，不通过改写或倒拨已执行迁移历史恢复。备份未在本次清理中删除。
