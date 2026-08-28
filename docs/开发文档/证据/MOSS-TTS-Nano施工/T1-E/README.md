# T1-E：媒体原子发布、不可变读取与可恢复 GC 证据

状态：**`READY_FOR_T1_GATE_REVIEW`（媒体/存储基础设施范围）**。当前字节通过 `76/76` 媒体单测；主代理又在 Alembic head `20260826_0015` 的隔离 PostgreSQL 18 上完成 current-head live suite `56/56`，其中媒体数据库 `11/11`、asset-scoped media `6/6`；0013 迁移另为 `2/2`。本文件不裁决 T1-GATE，也不声明播放器或产品 capability 已开放。

日期：2026-08-26（Asia/Shanghai）；工作包：`T1-E`（`PAR-C`）。

## 1. 已实现基础契约

| 风险 | 当前门禁 |
| --- | --- |
| 多个数据库 owner 指向同一物理 blob | asset-scoped canonical path、唯一物理 owner、发布和 GC 前行锁及完整身份核对 |
| 半写、覆盖或目录元数据未耐久 | staging 限长写入、hash/size 重算、0440、file/dir fsync、atomic no-replace publication |
| 发布后 DB 回滚留下孤立文件 | 确定性 asset path 与 re-adoption；同字节重试复用，身份不一致 fail-closed |
| GC 按路径盲删 | 持久 plan 固化 scope/backend/path/hash/size/generation/device/inode；删除前重新验证 regular/single-link/immutable |
| GC 与迟到引用竞态 | cover、voice、render、export、active-job 引用和 GC 在同一 media row 上串行化；只允许引用 ready asset |
| 路径、symlink、FIFO、hard-link 绕过 | root device/inode 固定、disjoint roots、`O_NOFOLLOW|O_NONBLOCK`、regular-file only、单 hardlink |
| HTTP 读取身份漂移 | GET/HEAD decision 在 200/206/304/416 前复核 state/scope/class/path/MIME/size/hash/inode，并固定 ETag/nosniff/private cache |
| 墓碑泄露路径或可伪造 | path-free HMAC tombstone，key/actor/id 有界，完整 generation 与 plan identity 校验 |

服务和数据库 helper 只参与短事务；大文件/模型/网络 I/O 不得在持锁事务内进行。

## 2. 当前字节验证

所有 live 写入均位于与正式库不同的 loopback disposable PostgreSQL 18，不挂正式数据库卷、正式媒体卷或模型卷。正式数据库仍为 `20260825_0009`，未迁移、未触碰。

| 验证 | 结果 |
| --- | --- |
| 当前无数据库组合单测 | `175 passed`；其中 `test_media.py` 为 `76/76` |
| `test_asset_scoped_migration.py` | `2/2 passed` |
| current-head 0015 live suite | `56/56 passed`，0 failed、0 skipped |
| `test_media_postgres.py` slice | `11/11 passed` |
| `test_media_asset_scope_postgres.py` slice | `6/6 passed` |
| `test_publication_postgres.py` | `1/1 passed`，完整原子回滚/re-adoption 用例重复两次均通过 |
| `test_crash_recovery.py` | `6/6 passed`，包含 lease/epoch/resource 与 GC 恢复 |

publication atomicity 用例实际验证：文件先按确定性 ID 发布；注入数据库事务失败后，render/job/attempt/media/link/model-run 全部回滚而文件保留；重试重新采用相同文件并在一个事务提交权威记录。它证明 T1 的 publication primitive，不冒充 T4 长期 Worker 已实现。

## 3. 当前 SHA-256

| 文件 | SHA-256 |
| --- | --- |
| `backend/narration/storage.py` | `17302a870d6ae31aa3d400a818095e3e7a90d42638e9a8778f9d37d7211c42a1` |
| `backend/narration/media.py` | `7a6d8358ddcbd9bb4d74acec22560f52e1e5f5bc4fb7068f766f7f2e8d368be2` |
| `backend/narration/publication.py` | `09ec2b404b73e61ab6e0ac6c223276e2e19092da66d06bb21050f10fbb4bb344` |
| `tests/narration/test_media.py` | `6322eb61dfaefee4d8892997f088d145d0f35a392f1a75c39ca6c0be56c756be` |
| `tests/narration/test_media_postgres.py` | `3d6b5ecb4a115915ebd89f64315b84176a10da00fd3b92f3bb507f568faabe5e` |
| `tests/narration/test_media_asset_scope_postgres.py` | `5e26ab14a49a2c789741de57016770cf054d7bca86243f012304fc17fdf31f8d` |
| `tests/narration/test_publication_postgres.py` | `ef73b71535696f234c032331f6d33a15cb5dfbfa9268dc893bfb32f72742965d` |
| `0013_narration_asset_scoped_paths.py` | `574762bfc63761cde77731118335549079758f221c9889e4ad0fdca8f95ec18e` |

## 4. 阶段边界与剩余风险

- 产品 HTTP 路由、鉴权、浏览器 Range/断线恢复属于 T2/T4 产品接线，不是 T1-E 基础设施退出项。
- 长期 scheduler/worker 属于 T4；T1 只需证明可由后续 worker 安全消费的任务、媒体和 publication primitives。
- 真实 WAV/MP3 解码、响度、听感与大规模导出性能在后续模型/产品门禁验收；本文件不做听感声明。
- Linux named-volume 的断电级耐久仍未由本包单独声明；当前实现遇到 inode/身份变化会 fail-closed 并保留恢复副本，不会自动误删。
- database role package 保持 secure HOLD、未接根 Compose；这是同一 PostgreSQL 的未来角色隔离，不是第二数据库。T1-GATE 可在明确 no-go 下保持 HOLD。
- capability 继续 false 是 T1 的安全状态；本文件不要求提前开放产品。

机器可读证据见 `validation.json`，固定文件摘要见 `hashes.sha256`。若集成失败，保留数据库、媒体和历史证据，使用 forward fix；不得回写迁移或清理用户卷。
