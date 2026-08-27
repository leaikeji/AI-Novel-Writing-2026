# 写作研究运行器

状态：源码候选；默认关闭；两次真实 X01 哨兵均未通过，当前阻断为公开 PawApp 流不提供可核验的 actual provider/model 与 usage。

2026-08-27 源码门禁：冻结合同/API/CLI 新增测试 `52 passed`，相关定向回归 `166 passed`，项目全量回归 `2376 passed, 116 skipped`；合同自检、Compose override 配置解析和 PawApp 打包通过。以上只证明运行器候选可进入真实哨兵，不证明模型侧链路或写作质量已经通过。

首次真实哨兵 run id 为 `mystery-ab-runner-sentinel-v1`。固定合同和路由预检通过后只派发 X01 一次，最终得到 HTTP 504，结果为 `0 completed / 1 failed`；没有正文、actual 模型或 token usage，运行器未重试。前后小说权威表计数一致，研究入口已恢复404，原生根页面、PawApp 注册表和项目健康接口均为200。该结果只证明超时失败被安全收口，不批准继续16样本。

## 作用范围

运行器只执行 `mystery-ab-20260827-v1` 已登记的16个项目合成样本。HTTP 不接受 prompt、题面、小说正文、文件路径、Agent、Skill、Provider、模型或采样参数；服务端不连接小说数据库，也不创建候选、revision 或故事事实。

后端固定使用 `ai-novel-writer` 与 `prose-writing`，在可信 `chapter_generation` 任务模式下禁止工具和持久化。调用前保存 effective 模型，调用后只从结构化 PawApp closing reply 的公开 usage metadata 获取 actual 模型与 token；缺失、不合法或 requested/actual 不一致时样本作废。运行器不使用 QwenPaw 内部 usage buffer。

## 默认关闭

普通 `compose.yaml` 不传研究开关，路由返回404。短期研究窗口使用独立 override：

```bash
docker compose -f compose.yaml -f docker/writing-eval.compose.yaml config
docker compose -f compose.yaml -f docker/writing-eval.compose.yaml up -d qwenpaw
```

研究结束后使用普通 Compose 重建 `qwenpaw`，移除开关：

```bash
docker compose -f compose.yaml up -d --force-recreate qwenpaw
```

启停共享 QwenPaw 运行环境属于串行操作；真实执行前必须先完成打包、安装与原生功能非回归，不能在其他专项正在操作唯一运行环境时切换。

## 主机命令

先验证冻结合同，不调用模型：

```bash
.venv/bin/python scripts/run_writing_eval.py verify-contract
```

真实运行必须明确承认模型调用成本。先做单个哨兵：

```bash
.venv/bin/python scripts/run_writing_eval.py run \
  --run-id mystery-ab-runner-sentinel-v1 \
  --sample X01 \
  --acknowledge-model-cost
```

同一 run 继续时必须显式 `--resume`。已有完整且哈希一致的样本会跳过；存在 dispatch 后无结果或失败记录时不会自动重试，必须保留旧 run 并另行裁决。

```bash
.venv/bin/python scripts/run_writing_eval.py run \
  --run-id mystery-ab-20260827-run1 \
  --acknowledge-model-cost

.venv/bin/python scripts/run_writing_eval.py status \
  --run-id mystery-ab-20260827-run1

.venv/bin/python scripts/run_writing_eval.py verify \
  --run-id mystery-ab-20260827-run1
```

## 证据

每个 run 保存 `plan.json`、`summary.json`、逐样本 prompt、正文、模型证据、硬门槛候选和匿名样本。模型失败、超时、身份缺失、模型漂移、保存中断和硬门槛失败都保留，不自动重抽样。

程序只直接判断空输出、NFC 后非空白字符数和明确包装；锚点、人物知识、视角、禁止新增、状态变化和悬疑机制仍需匿名人工复核。

## 超时诊断合同

2026-08-28 的源码修复改用公开 `ctx.chat_stream()`。服务端只记录事件类型、消息角色、内容块类型及首末事件耗时的有界计数，固定 `content_recorded=false`，不把推理、正文片段、工具参数或文件内容放进诊断响应。

每次结果或失败都必须如实记录：Skill 只是通过 `PawAppContext` 参数请求，工具限制只是 `prompt_only`，不能写成宿主已经强制禁用工具。失败响应携带 session id、开始时间和流式结构摘要；CLI 保存受64 KiB上限保护的 JSON 错误正文、HTTP状态、正文哈希和客户端耗时。该修复只补观测能力，不批准真实重跑。

本次诊断修复的模拟定向测试为 `54 passed`，项目全量回归为 `2436 passed, 116 skipped`；合同自检、Compose override 静态解析、Python 编译和 PawApp 本地打包通过。验证过程没有启用研究入口、安装插件或发起模型调用。

## 第二次流式哨兵

`mystery-ab-runner-sentinel-v2` 只派发 X01 一次。响应流于308.590秒完整结束，共14,492个结构事件；没有观察到工具调用类型，也没有触发600秒超时。随后模型身份核验失败并返回 HTTP 502，因为 closing assistant message 缺少 `qwenpaw_turn_usage`。运行器按合同没有保存正文、actual 模型或 token usage，也没有重试。

该结果证明流式观测已能区分“流没有结束”与“流结束后证据不足”，但也证明当前冻结成功条件无法通过公开 PawApp 合同满足。不得改用私有 usage buffer，也不得把调用前 effective 模型当作 actual 模型。其余15个样本继续停止。

运行窗口结束后研究路由恢复404，QwenPaw/PawApp/项目健康接口正常，TTS Sidecar healthy，原有 TTS 验证字段等值恢复。共享环境同时产生43条 TTS segment render 模型记录和两条 `tts_snapshot` 正文版本；行级类型表明它们来自并行朗读流程，不能写成评测运行前后总表计数完全一致。
