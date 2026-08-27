# 写作研究运行器

状态：源码候选；默认关闭，尚未完成真实哨兵验收。

2026-08-27 源码门禁：冻结合同/API/CLI 新增测试 `52 passed`，相关定向回归 `166 passed`，项目全量回归 `2376 passed, 116 skipped`；合同自检、Compose override 配置解析和 PawApp 打包通过。以上只证明运行器候选可进入真实哨兵，不证明模型侧链路或写作质量已经通过。

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
