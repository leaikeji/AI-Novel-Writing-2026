# 计划83 可达性、边界与发布审计

日期：2026-09-14（Asia/Shanghai）
性质：源码静态审计、第一轮精确清理、代码校验与正式环境热更新证据；不代表真实模型或文学质量验收已经通过。

## 方法

1. 清理前工作区为 clean；读取根 README、两级文档索引与计划81状态基线。
2. 后端排除迁移历史，以`plugin.py`为生产根解析 Python 静态 import 图，并用全仓精确模块引用、`backend/app.py`路由、`plugin.py`工具注册及历史替代计划复核。
3. 前端排除测试、声明和测试 harness，以`frontend/src/index.ts`为生产根解析静态 import／dynamic import 图；再检查被全局样式聚合器意外引入的孤岛样式。
4. 对候选逐一检查 Git 历史、生产调用者和仅测试引用。只有“生产不可达＋无字符串注册＋替代／未接线事实明确”的项进入删除。

## 清理前结果

| 范围 | 总数 | 从现行入口可达 | 初筛未达 | 最终动作 |
| --- | ---: | ---: | ---: | --- |
| 后端非迁移 Python 模块 | 223 | 199 | 24 | 排除 namespace 后移除18个生产／支持文件 |
| 前端生产 TS 模块 | 203 | 192 | 11 | 排除fixture后移除11个未接线文件 |
| 误接全局 bundle 的孤岛样式 | — | 1 | — | 移除`voice-lifecycle.ts`及聚合导入 |

第一轮合计移除30个生产／支持文件、7,435行；另从仍保留的生产文件移除583行手机／触控样式。移除14个仅覆盖孤岛的独立测试文件及1个空测试包标记，并从两个混合测试中删除退役分支；当前已跟踪差异合计删除12,174行，新增仅为测试措辞与文档。

主要替代／退出依据：

- MOSS说话人云分析、匿名身份操作和旧声音 brief 属于计划18／35／40历史链；现行Provider已由计划59／62迁至Qwen TTS，生产入口无引用。
- `embedding/evaluation.py`已有`evaluation_v2.py`，旧`embedding/renderers/`仅由自身测试引用，现行索引使用`embedding/chunking.py`及其正式入口。
- `writing_skills/dispatch.py`是计划58旧候选，现行入口使用`middleware.py`、`native.py`和后续语义编排。
- 前端工具轨在计划20证据中明确“暂不接线”且此后从未进入`index.ts`；大纲人物草稿目录、建书上下文副本、textarea auto-size同样只由内部测试引用。
- voice lifecycle面板／状态未接生产页面，但其样式被`narration/styles.ts`全局拼接，属于确定的无效bundle负担。

## 桌面边界

已移除所有生产TS中<=768px的viewport宽度media query和触控专属声明。保留840px以上桌面窗口规则、container query、桌面高度／超宽规则、`prefers-reduced-motion`、`forced-colors`和键盘焦点。

`@container anw-voice-library (max-width: 390px)`保留：它依据组件可用宽度而不是手机viewport，在桌面宿主侧栏与助手同时展开时仍可触发。

## 限制与下一步证据

静态可达不证明每条运行分支都被使用，也可能遗漏反射或字符串加载；本轮已用全量Python／前端测试、类型检查、构建、插件打包和正式桌面非回归补证。第一轮不删除仍可达但“可能很少用”的模块，也不改写迁移历史或审计证据。

正式桌面复查使用当前真实桌面浏览器`2552×1251` CSS viewport（DPR 2），覆盖宿主侧栏常驻、QwenPaw助手折叠和展开后的挤压路径；没有单独把结果外推为所有桌面尺寸均已人工验收。真实模型验收和Agent同模型A/B仍须使用冻结样本、调用上限与作者质量裁决完成。

## 当前验证结果

- 清理后静态图：后端实质性不可达0，前端生产不可达0；
- Python：3159 passed、329 skipped；
- 前端：163个测试文件、1552项全部通过；
- TypeScript类型检查、Vite生产构建、插件打包、`git diff --check`通过；
- 候选包内未发现本轮退役模块名；
- 通过QwenPaw公开CLI接口原位热更新正式环境；候选树与已安装树完全一致，产品与朗读健康状态均为`ready`，容器未重启，Agent模型／Skill／工具／prompt文件清单保持不变；
- 更新前精确恢复点：`/private/tmp/plan83-release-7GWuie`，包含已安装插件树、Skill状态、Agent选择、容器状态、活动快照与哈希；异常时可用其中`plugin-before`通过同一公开安装路径恢复；
- 刷新正式页面后，PawApp自身已注入样式中的<=768px viewport媒体查询、`touch-action`和`-webkit-overflow-scrolling`匹配均为0；宿主全局样式仍含自己的响应式／触控规则，本项目不越权修改QwenPaw上游；
- 正式桌面实测：助手折叠时工作台主区宽2210px；助手展开后主区宽1678px、助手宽584px，二者均可见，`document.scrollWidth === clientWidth === 2552`，无横向页面溢出；
- 浏览器无PawApp错误；仅观察到QwenPaw宿主既有`[moduleRegistry] Module not found: Chat`警告；
- 本轮没有调用模型，也没有改动小说内容；真实写作模型验收和Agent同模型A/B尚未执行。

## 独立复查（2026-09-14）

- 重新实现并复跑后端AST import图；首次复查脚本因把包级`__init__.py`错误记为`package.__init__`产生6个假阳性，修正归一化后为207个包／模块节点、200个从`plugin.py`可达节点、0个实质性不可达模块；
- 重新复跑前端静态 import 图：199个非测试TS／TSX节点中191个从`frontend/src/index.ts`可达，余下4个均为明确的测试fixture，不属于生产孤岛；
- 逐项复看删除测试：`assistant-layout.integration.test.ts`的矩阵只验证已删除工具轨与现行布局的组合，现行助手宽度／overlay／constrained合同仍由`assistant-layout.test.ts`和`assistant-pane.test.ts`覆盖；混合测试只删除了对应退役模块的分支；
- 修正文档中“开始移除”的过期措辞、总删除行数，以及“15个独立测试文件”的不准确计数；
- 第二次全量回归仍为Python`3159 passed, 329 skipped`、前端`163 passed`文件／`1552 passed`测试；TypeScript、Vite生产构建（203 modules）、插件打包和`git diff --check`再次通过；
- 正式环境只读健康复查仍为`status=ready`、数据库已连接、embedding与narration均`ready`。本次复查没有重新安装、重启、调用模型或修改作品数据。
