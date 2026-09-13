# G1冻结合同

日期：2026-09-13。作用域：计划74 V1.2；无schema迁移、无新依赖。

## 采用与保存

- 整章采用继续`adopt_candidate`；当前规则检查缺失／过期使用`PrivateLibraryConflictError(code="library_check_required", current={message, rules_sha256, report_id?, candidate_id?})`，API统一映射HTTP409。已经采用的候选先按范围校验并返回原结果。
- 当前政策读取`resolve_effective_lexicon_policy(session, novel_id, *, lock=True)`保持默认；`lock=False`只读取可信active作品，供扫描快照取数。取数之后释放事务再扫描，最终写回锁小说→候选／working copy→report并复核hash。LIST不得改变这个入口。
- `save_draft(..., library_application: SelectionLibraryApplication | None=None)`为加法参数。结构见`maintenance_contracts.py`及前端同名DTO：应用ID、job/attempt、基线version/hash、replacement hash、可选精确Diff段ID、报告ID/version。应用的完整正文必须由服务端持久job重新合成并与请求相等。没有元信息的手写保存／撤销保持原合同。
- ADOPT新增`selection_application.py`，提供`resolve_selection_application_source(session, novel_id, document_id, job_id, attempt, replacement_sha256, accepted_segment_ids)`，返回`(final_markdown, unchanged_baseline)`；unchanged_baseline为`(baseline_markdown,start_utf16,end_utf16)`。API检查和save_draft调用同一函数，不逆向导入API。
- 报告原始扫描不变；`decisions_json`加法追加应用事件`kind="application"`，包括application_id、input_sha256、output_sha256、revision_id或draft_version及时间。最终正文与应用事件同事务；重放不得覆盖新稿。保留选择先用现有decisions端点分批≤200、CAS保存；应用引用当前report version，不重发所有决定。
- 前端`AIApplyMeta.libraryApplication`传递到正文Adapter、原saveNow和恢复草稿。失败保持元信息，不静默退回无元信息保存。现有保存API不变，错误按type区分词库重查与正文CAS。

## 查询与UI

- `list_scoped_assets`加法参数`scope_filter=all|library|novel`、`enabled_filter=all|enabled|disabled`、`projection=full|summary`；原参数与默认兼容，limit默认50、最大100。无novel时不能使用novel范围／启用筛选。
- HTTP传query，助手保留search，在适配层映射；工具从可信access取得novel，不接受模型自报novel_id。返回原字段并加next_offset；工具资产查询复用同一服务。
- summary含原稳定列表字段及entry_count/detail_loaded=false，不含完整content/metadata/lexicon；full详情保持兼容且detail_loaded=true。列表页面不逐项取详情。版本／绑定计数批量查询。
- UI受控props：`filters?: LibraryQueryFilters`、`onFiltersChange?: (filters)=>void`、`total?: number`、`selectedAsset?: PrivateLibraryAssetView|null`、`detailLoading?: boolean`、`detailError?: string|null`。存在受控filters时assets已由服务端过滤；无受控props保留旧调用兼容。详情未加载时禁止编辑，归档已启用项允许停用；无当前书禁用启停。
- LIST新增`library-query.ts`提供`buildLibraryQuery(filters, novelId, offset=0): string`及可测试的分页／请求代次状态（实现细节自选但先回报主代理）；主代理在creative-center接线。
- UI新增`candidate-adoption.ts`，导出`createLibraryCheckDecisionPanel(React, antd)`组件。props为`report: LibraryCheckReportRecord`、`loadPage(offset): Promise<LibraryCheckReportRecord>`、`saveDecisions(report, keepHitIds, skipIncomplete): Promise<LibraryCheckReportRecord>`、`onComplete(report)`、`onCancel()`、可选`onLocateHit(hit)`。组件负责逐项选择、分页和分批保存；返回当前已完成／显式跳过报告，不负责正文提交或创建模型任务。整章与选区由主代理共用该面板。antd仅使用现有runtime字段及原生input checkbox。

## 所有权与执行

沿计划14.6：ADOPT只写采用/报告/新领域合成及其分配测试；LIST只写查询/查询工具与model/library-query及分配测试；UI只写workspace及candidate-adoption和就地测试；入口、正文Adapter/恢复、API、归档、部署和Git由主代理独占。所有子代理禁止安装、提交、生产写入或修改其他包文件。G1合同测试通过后派发；各包初期纯代码测试不接正式数据库，真实临时库集成由主代理串行完成。
# 汇合复核补充合同（2026-09-13）

- 启停的耐久幂等证据复用既有`LibraryChangeRequest`，不再覆盖可变binding的operation字段作为历史回执。按作品＋operation_key定位，asset/enabled/expected_binding_version参与输入hash；同输入重放只返回当前状态，不重放旧写入，不同输入拒绝，无变化动作也记录。业务与回执同事务。`source_json`明确标为结构化UI操作，独立UI session命名空间，不伪造聊天指令或AI授权；与通用维护回执兼容，未提供安全undo动作时不可宣称可撤销。既有证据保留／作品永久删除保护继续适用。
- 启用已生效时保持原固定版本及用法，不因重复true升级资料；启用状态与active绑定CAS版本分别投影，prohibited仍返回真实绑定version。
- 自动保存定时器冻结文档及访问代次；等待旧请求完成的普通保存只取当前最新稿，受控AI快照独立。所有异步恢复CAS返回后再次验证访问代次与本地稿身份。
- 刷新发现的恢复稿先进入待作者选择状态，不能作为活跃保存意图或被继续输入覆盖。载入冲突的服务器稿仍保留原恢复全文并等待选择；明确转为手写时展示待保存与将被替换全文，按确认时服务器基线CAS提交，服务器再次变化即停止。
