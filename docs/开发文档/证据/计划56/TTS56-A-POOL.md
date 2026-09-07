# TTS56-A-POOL 通用音色包恢复审计

状态：审计后的 A1–A5 已按主代理 C0 派发修复；隔离 PostgreSQL 专项及 API 回归通过。没有操作 Docker、正式数据或真实模型；未部署、未裁决全链最终通过。

日期：2026-09-03；工作包：`TTS56-A-POOL`；审计原始基线：`main@0a686c2`。第2、3节行号及探针结果保留修复前事实；当前结果见第6节。

## 1. 范围与裁决

检查 `generic_voice_pack_service.py`、`generic_voice_generation.py`，并只读对照当前 API、0040、scheduler、前端通用包组件与计划55证据。当前能力契约 `/4`、迁移 `0040`、公开 DTO／状态集合均不需要为以下问题新增版本。

**建议修复范围仅为现有通用包服务与对应测试，不重做24槽目录、生成 runtime 或任务框架。**主要缺陷是异常／重放状态收敛；正常逐槽生成和完整包投影已有可复用证据。

## 2. 已确认缺陷

### A1｜P1：崩溃回收只终结子命令，包永远停在 building

- 源码：`backend/narration/generic_voice_pack_service.py:955`（`terminalize_job_in_session`）。
- 路径：`_enqueue_next_slot` 给每个 job 配置 `max_attempts=1`；工作进程崩溃 → lease 过期 → scheduler 对账转 job 为 `dead_letter` → terminalizer 只把子 command 转为 `failed`。
- 结果：slot 仍 `generating`、pack 仍 `building`。`_load_resource` 继续投影为非终态 building；`build` 直接返回该旧包；`retry` 又拒绝 building。只有作者先取消再继续才能绕过，不符合失败可重试／启动恢复。
- 证据：`scheduler.py:257`–285 确实在同一对账事务调用该回调；内存替身探针运行真实 terminalizer，输出 `child_state=failed`，只查询 `BackgroundJob`，没有加载或更新 slot／pack。
- 最小修复：在同一事务收敛仍由该 command 拥有的 slot 与仍 building 的 pack；保留已取消／拒绝／退役状态，不让迟到失败覆盖继任包。与正常 `fail` 共用一个窄的领域终结 helper，避免复制终结规则。
- 必补测试：真实隔离 PG 领取→租约过期→scheduler 对账，公开资源变为 terminal/retryable，retry 创建继任且复用已成功槽；重复 terminalize、旧命令迟到、取消后回收不复活。

### A2｜P1：重新生成先提交退役，再验证建包，失败会留下没有继任的退役包

- 源码：`generic_voice_pack_service.py:567`–585；`build` 在392–394验证键长度。
- 路径：regenerate 调用 `reject`（独立提交），再调用 `build`（另一个事务）。第二步输入验证／数据库失败不回滚第一步退役。
- 可确定反例：HTTP接受128字符 `Idempotency-Key`（`voice_features_api.py:1298`–1302）；内部拼成 `generic-regenerate:<slot>:<key>` 后超过128，`build` 抛 `ValueError`。此时 active 包已在 `reject` 中提交为 `retired_for_new_use`，新章节无法使用该包，继任并未创建。
- 内存探针：128字符合法HTTP输入输出 `ValueError reject_called_before_failure=1`；使用真实 regenerate/build 入口，仅将数据库读与 reject 替换成观察桩，不涉及数据库写入。
- 最小修复：先校验公开输入、slot与scope；使用有界确定性内部身份；把拒绝目标槽、旧包退役、继任创建放入一个短事务。第二步任何异常均回滚。**真正拒绝后暂不允许新章节用旧包是现行约定，不是本缺陷；缺陷是操作失败也退役。**
- 必补测试：128字符header；继任插入／enqueue失败注入后旧包和槽完全不变；普通成功只换目标槽；不改旧Edition。

### A3｜P2：相同重生成请求响应丢失后，CAS先于幂等找回

- 源码：`generic_voice_pack_service.py:574`–585。
- 路径：以expected=A、key=K成功创建B，HTTP响应丢失；原请求expected=A、key=K原样重发。latest已是B，首先触发“version changed”，未到确定性build身份的replay查找。
- 内存探针：`CAS-rejected-before-replay build_called=0`。
- 结果：重复请求本应找回同一命令，却返回冲突；它不是并发作者新选择。不会凭本反例直接推导音色重复生成，但阻断安全的响应丢失恢复。
- 最小修复：在目标拒绝／CAS之前找回当前key既有继任，并验证slot／前驱范围；保持不同输入不误复用。优先复用现有确定性UUID与predecessor字段，不新增父表。
- 必补测试：继任building与active两种状态下原请求重放；旧key不得意外退役已经完成的继任；真CAS漂移仍失败且零写入。

### A4｜P2：非active包点击“重新生成”不会使目标槽失效

- 源码：`generic_voice_pack_service.py:579` 只在active状态调用reject；`build:476`–485继续复用validated/reused槽。
- 路径：A已有若干validated槽，另一个槽失败导致pack failed；作者不喜欢其中已生成的X，点该行“重新生成”。前端 `generic-voice-pack.ts:600`–610提供这个入口。regenerate不标记X拒绝，只build继任；X满足can_reuse而原样复用，实际重生成的是失败槽。
- 对building候选也有同类无效操作：入口存在，但build直接返回building旧包，目标不会重做。
- 内存探针确认failed包regenerate的 `target_invalidations=0`，直接调用build；复用结果由can_reuse分支可确定推导。尚未做PG完整反例。
- 最小修复：在允许的候选状态内，对明确请求的目标槽执行同事务拒绝／继任；若正在生成时不允许操作，必须给明确可恢复状态而非成功返回旧包。保持已验证非目标槽复用，不为一次拒绝重建整包。
- 必补测试：failed包validated目标重做；building包已成功目标的处理；其他23槽按身份复用；未知slot零写入。

## 3. 并发与次要审计发现

### A5｜P2：首次／继任build没有首写者串行化

`build:404`–436执行查replay、查latest、取version+1、insert，未锁定稳定workspace资源。并发两个首次请求会同时选version=1，再由0040的PK或 `uq_generic_voice_pack_version_number` 拒绝一个；`_transaction`只回滚并重抛，未返回赢家命令。库约束防止了双包落库，但其中一个合法请求会失败。

此结论为源码并发交错推导，**不是已运行双连接PG复现**。建议和A2同一事务收敛修复：在固定workspace／语言建立一个短事务串行点（已有行锁或事务级advisory lock），不新增表／服务；保持job→command→pack→slot现有锁序，避免在failure路径引入反序。`fail:928`先command再 `fail_attempt`锁job，与cancel/publish的先job顺序相反，需同批补双连接测试并统一锁序。

### 尚不单独升级为功能缺陷

- reused槽创建没有复制两个 `*_audio_sha256` 列；当前可信媒体仍能沿voice_version／MediaAsset找回，未发现播放读取这两个槽列，不据此声称已损坏。可在同一小补丁补齐审计镜像字段，测试复用hash一致；不新增字段。
- `generic_voice_generation.py`的目录严格解析、scope、指纹、状态机与validate/reuse单测本轮通过，未发现需改动纯领域模块的实际问题。
- cancel把pack变为superseded，公开command显示cancelled；前端按“继续准备”调用新build，现有新key路径正确，不需要新增cancelled pack状态或新API。
- `ensure_novel_projection`先锁Novel、只选active完整pack、同事务投影24槽，旧pool退役不改旧Edition；现有正常路径无需重写。补继任成功／失败情况下的投影验证即可。
- active包被作者真实reject后变retired、所有旧音频保留，是已批准行为，不应改成删资产或偷偷继续新用途。

## 4. 实际验证与证据复用

执行：

```text
.venv/bin/python -m pytest tests/narration/test_generic_voice_generation.py tests/narration/test_generic_voice_pack_postgres.py
13 passed, 4 skipped in 0.52s
```

4项PG因为未配置 `TTS_TEST_DATABASE_URL` 跳过，不计PASS。未创建测试库、未探测正式连接。另运行无数据库／无模型的四个内存探针，结果见A1–A4；它们证明控制流，不能代替PG事务和并发验证。

可复用 [`TTS55-FINAL-REVIEW`](../计划55/TTS55-FINAL-REVIEW.md) 第4节的：

- v9完整24槽机器证据、23槽复用／单槽替代、最终06精确hash听检。
- v5/v8/v9新Edition按完整pool切换，旧Edition仍ready16/16。
- VoiceGenerator→Nano真实双模型成功、严格互斥。

这些覆盖成功路径；不覆盖本报告新增的崩溃回收、HTTP响应丢失、合法长key与双连接竞争。目录／模型不改时无需重新在隔离环境跑整包24次；以现有Host/Nano替身在真实PG覆盖状态和事务，必要少量真实槽做代表补验，再由主代理处理正式包。

## 5. 最小修复派发建议

唯一需写产品模块：`backend/narration/generic_voice_pack_service.py`。测试：`tests/narration/test_generic_voice_pack_postgres.py`（可增加无DB控制流用例）；本报告追加修复证据。`generic_voice_generation.py`／目录／公共DTO／ORM／0040／API暂不改。

合并A2/A3/A4/A5为现有事务helper重构，避免分别叠四套分支；A1和正常fail共用领域收敛。主代理提供精确隔离PG URL后，运行本包专项并补双连接竞态；主代理统一API回归／最终集成。没有必要新增migration。报告提交时仍为审计结论，等待主代理冻结后的修复派发。

## 6. PAR-C 修复与隔离验证

主代理派发后仅修改本报告及上述服务／PG测试文件，未修改纯领域、目录、API、DTO、ORM或迁移。

修复内容：

- A1：正常fail、scheduler lease回收、取消ack复用同一终结投影；job→command→pack→slot同事务收敛。仅修改仍属该命令且仍building的包／槽，迟到回调不覆盖继任或作者拒绝状态。
- A2–A4：提取 `_build_in_session`／`_reject_in_session`；拒绝目标、退役旧包和创建继任一次提交。输入先验证、确定性继任先查replay后做CAS；保留旧0040的UUID命名公式，128字符公开key不因内部前缀报错。failed/building包也明确重做作者指定槽，其他已通过槽复用。
- A5：固定workspace／zh-CN事务级advisory锁保护首次建包及短管理操作；publish同样在取得行锁前领取该锁，避免取消和下一槽enqueue交错。模型调用期间不持有该锁。正常fail改为先锁job，再锁command，与cancel一致。
- 双连接测试另外发现运行中cancel重放会把 `cancel_requested` 提前写成 `cancelled`；现保持cancel_requested直到worker ack／lease对账，不让重复请求破坏取消围栏。
- reused槽同步继承已有的reference／validation hash，不造新资产。

### 6.1 明确重做与技术重试的seed语义

PG替身稳定生成同一音频，暴露出旧“重生成仍用同seed”会撞既有Voice Version指纹唯一约束，也不能有效表达作者要求换声音。主代理已明确批准以下窄修复：

- 冻结目录／描述均不改；只有显式regenerate，或持久slot为rejected后继续／重试，创建目标的新不可变Draft。
- `seed = int(canonical_sha256({schema_version: generic-voice-regeneration-seed/1, command_id: packUUID, slot_key, counter}), 16) % 2^63`。counter从0开始，避开目标历史所有Draft seed、当前各槽seed及目录seed；新seed确定且在公开合法范围。
- 指纹直接调用现有 `_design_fingerprint`，继续包含真实seed、instruction hash、目录与taxonomy、VG runtime／参数和Nano身份；没有给旧fingerprint加随机盐。
- 同请求通过持久UUID找回同一个Draft／seed；技术失败、取消后继续保留原Draft参数。其他已接受槽，即使此前经重生成，其实际Draft和seed也保持不变。
- 实际seed随既有 `VoiceGeneratorWorkItem/HostRequest` 传出并存入Voice Version；生成命令继续关联不可变Draft和ModelRun。无需新增协议字段、表或版本。
- 即使音频字节相同，作者这次明确换seed是真实不同模型输入，其design fingerprint相应不同；不伪造音频变化或主观听感通过。

### 6.2 实际测试

由主代理提供并独占分配的隔离库：`127.0.0.1:58857/ai_novel_world_2026_tts_test`，已核对head0040；测试凭据未写入证据。无正式连接、无模型调用。

```text
TTS_TEST_DATABASE_URL=<主代理分配的隔离连接> .venv/bin/python -m pytest \
  tests/narration/test_generic_voice_generation.py \
  tests/narration/test_generic_voice_pack_postgres.py \
  tests/narration/test_voice_features_api.py

36 passed in 12.85s
```

其中13项纯领域、14项真实PG、9项API；PG项本次没有skip。覆盖：普通fail、真实scheduler过期dead_letter回收、旧failed子command收敛、重复终结、取消ack与迟到failure；24槽fake模型完成后重生成的插入/入队失败原子回滚、合法128key、129key零写入、building/active重放、真CAS冲突、23槽复用和hash；部分包目标重做；同request seed稳定、不同request/前seed避重、技术retry seed不变、显式reject继续换seed；双连接同／异key首写者、cancel与fail竞争。

双连接用例要求明确的独占空白隔离库，使用真实commit与15秒statement/10秒lock timeout；结束时只删除自身精确UUID对应的无媒体测试行。其他PG用例维持原外层事务回滚；未移除任何正式或作者媒体。

Python compile检查通过。本包不执行Git操作，最终diff、全量回归与发布由主代理统一检查。真实新seed听感、正式24/24、真实UI/模型补验仍属于主代理后续步骤，本报告不代判。
