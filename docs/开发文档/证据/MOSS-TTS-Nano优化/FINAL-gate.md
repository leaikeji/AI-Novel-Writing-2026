# 计划 33 MNX-FINAL 汇合记录

状态：**2026-08-29 源码、数据契约、全量自动化、构建、打包和冗余清理已通过；隔离 QwenPaw 安装因 Docker Engine 无法启动新容器而阻断。本次不进行长期数据库迁移、长期 PawApp 切换、Git 提交/推送或真实私人媒体删除。**

## 1. 能力裁决

| 独立能力 | 候选结果 | 发布结果 | 理由 |
| --- | --- | --- | --- |
| P0：18 官方 preset 直用 | 源码、`0031`、18 项隔离真模型短句与契约通过 | `HOLD_INSTALL` | 未迁移长期库，新 bundle 未完成隔离安装/浏览器验收 |
| P1：设置、人物覆盖、播放器 | 源码接线、前端全量、typecheck/build 通过 | `HOLD_ENVIRONMENT` | Docker Engine 阻止隔离 QwenPaw 安装，不用旧 18088 bundle 代替验收 |
| P1.5：Nano 高级实验参数 | decode v2 后端契约候选通过 | `HOLD` | worker PostgreSQL 夹具与实验版本产品 API 闭环未完成，入口保持隐藏 |
| P2-VG：根据人物生成专属音色 | 完成官方/本机尖峰 | `NO-GO` | 当前 M4/16 GiB 没有安全资源余量；页面降级为一键/批量自动分配官方音色，不冒充生成 |
| P2-DEL：私人音色删除 | `0032`、完整状态机、精确资产计划、三崩溃恢复与 UI 候选通过 | `HOLD` | 持久 grace/重启对账 worker 和服务端 eligibility 投影缺失；UI 未接线，HTTP 路由 fail-closed |
| W6 冗余删除 | `RED-008/009/010` 已精确删除 | `PASS` | 旧人物选择器 CSS、旧设置/覆盖组件及重复失败列表 CSS 零引用；替代回归通过 |

## 2. 实际验证

```text
.venv/bin/python -m pytest
3093 passed, 138 skipped, 2 warnings

pnpm test
102 test files passed, 920 tests passed

pnpm typecheck
PASS

pnpm build
PASS (132 modules transformed)

.venv/bin/python scripts/package_plugin.py
PASS: build/ai-novel-world-2026

tests/test_skill_contract.py + tests/test_qwenpaw_integration_contract.py
123 passed

docker compose config --quiet
PASS

git diff --check
PASS
```

额外 PostgreSQL 证据：`0031/0032` 在隔离 PostgreSQL 18 完成升级、回退与重升级；删除聚焦组合无失败，物理删除专项 8 项通过。Sidecar 源码变更后的 Dockerfile 防篡改 SHA-256 已同步，对应镜像契约测试通过。

## 3. 隔离安装阻断证据

- 最终重打包候选 tree SHA-256：`9b32c18a08e3f688f6636eb1918e1658fc93a3dcc58bc164a09c3d8eee221aa7`，dry-run 通过。
- 真实生命周期 runner 以两个独立 run-id 对自审前候选 `e87a83ac…d3d76` 执行，都在 `start-postgres` 阶段的 Docker start API 超时；容器为 `created`、无日志、无 OOM/地址冲突/数据库错误。
- 完全脱离 runner 的最小 `docker create` + `docker start` 也在同一 Docker Engine start API 失败，证明当前阻断不是 PawApp 安装包或迁移导致。
- 两次 runner 都完成精确清理；最小诊断资源也逐项删除。无残留计划 33 容器、卷或网络。
- 最终候选的 lifecycle dry-run 验证了四次公开安装/卸载操作、无主机端口、无 bind mount、候选完整性重校验和精确清理拓扑；它不替代 real run。

## 4. 未执行和恢复

- 未做新 bundle 真实浏览器矩阵和安装/升级/卸载实运行，原因是上述 Docker Engine 阻断。
- 未修改 `127.0.0.1:18088`、长期 `15432`、长期 QwenPaw/Sidecar/PostgreSQL 容器或数据卷。
- 未提交或推送 Git。`frontend/dist`与 `build/` 是本地生成物，不作为手工源码交付。
- Docker Desktop 恢复后，应从当时最新 tree 重新构建/打包，再重跑 real lifecycle 和规划矩阵；不应复用本记录的旧生成包。
