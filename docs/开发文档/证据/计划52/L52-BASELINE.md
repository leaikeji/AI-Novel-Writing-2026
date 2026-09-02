# L52-BASELINE：施工基线冻结

日期：2026-09-02（Asia/Shanghai）
状态：已完成（只读核验；未读取真实小说标题或正文）

## 1. Git 基线

- 分支：`main`
- HEAD：`4306b68059549f5ab4b4d7a046dda893c250adaa`
- tree：`15defa4621abac320c7c87dfa0db40f391380eb6`
- Alembic head：`20260902_0038`
- 本轮开始时已有 dirty 文件：
  - 计划 52 文档及两个文档索引；
  - `frontend/src/narration/character-voice-roster.test.ts`；
  - `frontend/src/narration/styles/t2-c.ts`；
  - `frontend/src/styles.ts`；
  - `frontend/src/workbench-container-layout.test.ts`。
- 后四个前端文件不是计划 52 的既有规划改动，保持原样，不覆盖、不重置、不暂存。

## 2. 长期运行态只读事实

- PostgreSQL：`pgvector/pgvector:0.8.6-pg18`，容器健康。
- QwenPaw：运行时容器健康；PawApp `ai-novel-world-2026` 已启用、已加载，版本 `0.4.0`。
- TTS sidecar：容器健康。
- Embedding 配置：schema `embedding-config/1`，配置 version `32`，Provider `aliyun-bailian`，协议 `dashscope-native-v1`，模型 `qwen3.7-text-embedding`，维度 `2048`，连接状态 `ready`。
- active generation：编号 `12`，评测状态 `passed`；无 candidate generation、无 previous generation。
- 小说数：3。本证据只记录授权和索引聚合状态，不记录标题、正文或其他创作内容。
  - 1 本：授权 `granted`，告知版本 `novel-embedding-consent/2`，`writing_query_authorized=true`；索引 `ready/current`，3 source、31 chunk、0 failure、0 pending refresh，存在本地向量。
  - 2 本：未授权，`writing_query_authorized=false`；索引 `not_authorized`，全部 corpus 为 disabled。

## 3. 事实差异与施工裁决

计划审计阶段曾记录“3 本均未授权、向量检索未启用”；施工基线已经变化，不能再用旧事实指导实现。计划正文已同步改为“1 本已授权、2 本未授权”。

这项变化不改变架构裁决：StoryFact 账本仍是唯一权威，向量索引仍是可重建派生数据。`L52-G0` 仅使用隔离测试库与合成小说，不使用上述真实小说做压力测试，不触发云端 embedding 或正文模型调用。

## 4. 下一闸门

只有 `L52-G0` 输出 100 万／500 万字合成样本的查询形状、响应体、耗时、峰值与检索质量证据后，才冻结 `L52-CONTRACT` 的候选上限、Context 选择范围、Prompt 预算和是否需要 schema／索引变更。ANN、迁移和长期发布尚未获准。
