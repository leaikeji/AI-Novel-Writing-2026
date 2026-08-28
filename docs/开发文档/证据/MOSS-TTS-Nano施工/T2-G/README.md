# T2-G 隐私、复核规则与运行状态施工证据

> **2026-08-26 主集成更新：** 本包已经接入 `backend.app` 和共享 reading 页面。后端授权红队随后收紧两处边界：撤销云同意要求 configure 权限；锁定音色同时要求声音资产管理和权利确认权限。T2 capability 下八项永久 NO-GO 均在 store 前阻断。当前 `test_reading_privacy.py` 为 36 passed；后端全量为 729 passed / 87 skipped。真实 QwenPaw／浏览器仍待 [T2-GATE](../T2-GATE.md)，所以这不是阶段放行声明。

> 历史局部状态：**T2-G 当时的局部施工候选已完成、尚未接入 T2-GATE；该状态已被上方主集成更新取代。**
>
> 日期：2026-08-26
>
> 工作包：T2-G（PAR-C；本包唯一写 Owner 为主代理）

## 1. 结果与事实边界

本包完成了作品级朗读设置、范围覆盖、云端最小上下文授权、人物音色绑定、总览聚合、复核/隐私规则面板和运行状态面板的局部实现。它们已经通过窄测试和跨 T2 模块回归，但尚未安装到 `backend/app.py`、共享前端入口或真实产品页面，因此不能表述为用户当前已能使用。

- 正文分析默认 `local_rules_only`；切换 `cloud_assisted` 必须同时满足独立 capability 和当前作品的有效授权。
- 云端授权使用独立 POST/DELETE，不混入普通设置 PUT；创建使用稳定幂等键，撤销使用 `consent_id + expected_version`，历史记录不物理删除。
- 唯一可消费的告知版本是 T0 冻结的 `narration-cloud-consent/1`；未知/旧版本不能开启云端模式。撤销后的请求返回 `CLOUD_CONSENT_REVOKED`，与从未授权区分。
- 授权只覆盖说话人不确定性分析和 `uncertain_segments_with_minimal_context`；前端没有第二个 provider/model 选择器，创建授权时两者固定为 `null`。
- 设置 PUT 是完整 replacement + CAS；没有变化不递增版本。播放速度和音量以有界十进制字符串持久化，再严格恢复为 wire float，避免非规范 JSON 指纹。
- 范围覆盖按 novel/volume/chapter 复验所属作品；disabled replacement 物理删除当前覆盖行，不伪造版本零持久记录。
- 人物音色绑定只接受同作品/全局可用 profile、已锁定且质量通过的 version 和当前有效 rights；修改只影响后续脚本/Edition，不改历史 Edition。
- 总览只汇总当前作品的 active 人物、合法绑定、24 槽真实就绪数、缓存、任务与运行态；已配置但权利撤销的音色不计入“锁定可用”。
- Runtime `ready` 必须同时具备技术启用、Sidecar 可达、模型 ready、64 位 fingerprint、精确 `moss-tts-sidecar/1.1` 且无错误 reason；任何矛盾都降为 unavailable，产品可见性固定为 false。
- UI 在 capability HOLD 时连草稿控件也禁用；旧授权、跨作品响应、CAS 冲突和卸载中的请求都失败关闭。撤销授权不依赖 cloud capability，撤销后在本地准备切回 `local_rules_only`，仍需作者显式保存。
- 磁盘、缓存、人物覆盖、通用音色覆盖、失败任务和模型状态均来自总览 wire 响应，不推测、不伪造“可用”。

## 2. 实际文件

1. `backend/narration/privacy.py`
2. `tests/narration/test_reading_privacy.py`
3. `frontend/src/narration/reading-rules-panel.ts`
4. `frontend/src/narration/reading-rules-panel.test.ts`
5. `frontend/src/narration/reading-status.ts`
6. `frontend/src/narration/reading-status.test.ts`
7. `frontend/src/narration/styles/t2-g.ts`
8. `docs/开发文档/证据/MOSS-TTS-Nano施工/T2-G/README.md`

本包没有修改 Alembic、冻结 DTO/API、共享前后端入口、workbench、Docker、依赖、正式数据库或用户媒体。

## 3. 冻结输入复核

| 只读输入 | 冻结 SHA-256 | 当前 SHA-256 | 结果 |
| --- | --- | --- | --- |
| `backend/narration/schemas.py` | `1e189e812cf674b0d9457328d4e74e95fda57a67b62a83f99eb31d299633fdbd` | 同左 | PASS |
| `backend/narration/settings_api.py` | `05b1a6be9ab58d30ccb12d143033a96aa8feb9fec7a6ed7ad1a6560894505378` | 同左 | PASS |
| `frontend/src/narration/contracts.ts` | `9a62723164027da7607ee4df0dc39bd61e9c21e89519d6cfb13352dfb66fc5ec` | 同左 | PASS |
| `frontend/src/narration/api.ts` | `2c675603fe7e19b0d2dcf362015a432a2fe1cf36920b4096bf52c8a479b9dce8` | 同左 | PASS |

## 4. 关键状态与安全结果

| 状态 | 可见结果 | 可执行动作 | 不变量 |
| --- | --- | --- | --- |
| 产品/设置 HOLD | 配置和稳定 reason code 只读 | 无设置草稿、无 PUT | 技术 ready 不翻转产品 capability |
| local 默认 | “仅本地规则” | 可保存复核策略 | 正文外发为 0 |
| cloud 未授权 | 云端选项禁用/阻断 | 明示告知后独立授权 | 不把选择 radio 当授权 |
| cloud 有效授权 | 当前 notice 与最小范围 | 可选 cloud、可撤销 | 不携带参考音频/整章/完整人物库 |
| cloud 旧 notice | “记录需重新确认”并准备 local | 先撤销旧记录，重新授权 | 旧告知不能继续消费 |
| cloud 已撤销 | 明示后续不外发 | 可保存 local；可新建新 consent | 旧 consent 不复活、不改写 |
| 设置 CAS 冲突 | 安全 alert、要求刷新 | 不自动覆盖 | 旧设置保持权威 |
| 作品 scope 漂移 | 拒绝显示/应用 | 刷新 | 其他作品数据不进入当前 UI |
| Runtime 证据矛盾 | unavailable + 稳定 reason | 无模型动作 | 不补造 ready/protocol/fingerprint |
| 音色权利撤销 | 仍显示已配置数量，锁定可用数下降 | 新绑定被拒绝 | 历史 Edition 不变 |
| 缓存 runtime 缺失 | 零派生量 + unavailable capability | 无清理 | 不伪报删除或可回收空间 |

## 5. 测试与审计记录

### 5.1 本包目标

| 命令 | 实际结果 |
| --- | --- |
| `.venv/bin/python -m pytest tests/narration/test_reading_privacy.py -q` | PASS，21 passed |
| `pnpm exec vitest run frontend/src/narration/reading-rules-panel.test.ts frontend/src/narration/reading-status.test.ts` | PASS，2 files / 17 tests |
| `pnpm typecheck` | PASS |
| `.venv/bin/python -m py_compile backend/narration/privacy.py` | PASS |

覆盖项包括默认/损坏设置、CAS/no-op、完整替换、云端幂等/撤销/重授权、旧 notice、actor/provider-model 漂移、scope 覆盖删除、人物绑定与历史影响、权利撤销、人物覆盖率、Runtime fail-closed、29 operation 所有权、事务 commit/rollback、前端 HOLD、重试幂等键、作品 fencing、AbortController、键盘焦点样式和窄屏 CSS。

### 5.2 跨 T2 回归

| 命令/范围 | 实际结果 |
| --- | --- |
| settings contract/API、voices、voice pool、pronunciation、privacy | 除 T2-H 预先写入的 1 个 T2-GATE 接线红测外，其余 151 项通过；该红测精确要求 `backend.app` 安装 router/factory 并对称卸载 |
| contracts/API、reading B–G、character voice、voice source/pool、pronunciation/cache | PASS，11 files / 105 tests |

上述单一红测是 T2-GATE 的既定测试先行门禁，不是本包偷偷改为 green 的局部职责。T2-GATE 接线后必须将其转绿。

### 5.3 只读审计发现并修正

1. 初版 coverage 在读取 rights 前解引用变量；已改为先取记录并补“有效→撤销”覆盖率回归。
2. 初版 ready 投影会接受缺失/错误 protocol；已改为 exact `moss-tts-sidecar/1.1` 且不接受 ready+reason 矛盾。
3. 初版撤销与从未授权共用 `CLOUD_CONSENT_REQUIRED`；已区分冻结错误码 `CLOUD_CONSENT_REVOKED`。
4. 初版授权消费未固定冻结 notice；已拒绝未知版本，并复验 actor、provider/model 配对、confirmed/revoked 证据。
5. 初版前端 HOLD 只禁用保存按钮但允许改草稿；已将两个 fieldset 和授权确认一并绑定产品/设置门禁。

## 6. T2-GATE 接线契约

### 6.1 后端

1. `backend.app` 只在 PawApp 生命周期中 include 已冻结的 `narration_settings_router`；使用公开 PawApp 边界，不占用或覆盖 QwenPaw 上游核心路由。
2. startup 用 `install_narration_settings_backend_factory(...)` 安装 `build_narration_settings_backend` 的窄 factory；shutdown 使用同一 identity 调用 uninstall。重复安装/卸载必须可验证且不访问 QwenPaw 私有数据库。
3. SQLAlchemy mutation 由 `TransactionalNarrationSettingsBackend` 保证一次业务动作一个短事务；外部缓存清理保留 T2-F 的独立两阶段事务，不进入路由长事务。
4. T2-GATE 必须注入真实、已验证的 `SqlAlchemyNarrationCacheRuntime` 依赖；不能以空成功替代缺少 secret/storage/session factory。缺失时保持 `STORAGE_UNAVAILABLE`。
5. 产品 capability 只能在 T2-GATE 完成 API、UI、授权、浏览器和隔离数据库验收后统一翻转；局部模块通过不能单独翻转。

### 6.2 前端

- 导出并组合 `createReadingRulesPanel(React, api?)`、`createReadingStatus(React)`；将它们作为 reading 页面 section 内容，不新增第二套 React/路由/模型选择器。
- 将 `T2_G_NARRATION_READING_RULES_STYLES` 只汇入 `frontend/src/narration/styles.ts`，保留局部命名空间。
- settings/authorization/capabilities 必须来自同一个、已验证 novel overview；父组件收到保存/授权回调后刷新同一作品聚合。
- 真实 React unmount/作品切换负责触发 effect cleanup；T2-H/T2-GATE 验证焦点、键盘、受限宽度与窄屏。

## 7. 未验证与保留项

1. 尚未在 T2-G 局部包中连接真实 PostgreSQL、PawApp 生命周期或真实缓存媒体盘；由 T2-H/T2-GATE 在隔离环境完成。
2. 尚未做真实浏览器截图、屏幕阅读器和触摸设备验收；当前只通过结构化 a11y 与响应式样式测试。
3. 云端授权只是设置层契约。T3 worker 在真正外发前、外发返回后仍必须再次读 consent，并实现撤权竞态和 requested/actual 模型证据；T2 不伪称已经外发或完成说话人识别。
4. 当前 fixed local owner/workspace 是个人版结构隔离，不是多用户认证。未完成宿主同源/安装生命周期验收前，产品 capability 保持 HOLD。
5. 磁盘状态是服务端快照；本面板不自创空间阈值。真实不足阈值、配额和回收动作属于 T2-F runtime/T2-GATE 证据。

## 8. 回退

本包没有 schema、迁移、依赖、共享入口或用户数据变更。T2-GATE 前可通过移除第 2 节文件回退。接线后必须先卸载 backend factory/router 绑定并从共享前端组合/样式中移除 T2-G 导出，再回退局部模块；不得删除 PostgreSQL、用户正文、云端授权审计行、音色、媒体卷或历史 Edition。
