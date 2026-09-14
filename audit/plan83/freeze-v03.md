# 计划83 V0.3 冻结合同

日期：2026-09-14（Asia/Shanghai）
状态：`R0_PASS`；用户已批准开始执行W3／W4，尚未修改正式Agent或调用模型。

## 正式环境与不变量

- QwenPaw：2.2.1；PawApp：0.4.0；正式入口：`http://127.0.0.1:18088`；只读健康为`ready`。
- 专用Agent：`ai-novel-writer`；effective模型：`bigmodel / glm-5.3-flash`。
- system prompt清单：`AGENTS.md`、`SOUL.md`、`PROFILE.md`、`AI_NOVEL_WORLD.md`。
- 12项小说Skill当前全部启用。
- 公开工具清单共35项，33项启用；`append_file`与`delegate_external_agent`禁用。完整名称与开关必须在A/B前重新读取并进入短期私密快照；模型、Skill和工具均为只读不变量。
- 正式专用prompt读回：14,932字节，SHA-256 `8dd5348bf8d90d2908e0a0b60d92a9d340b91f7da228ae49ddd1a75a73ef2fd9`；与仓库源移除唯一末尾换行后的字节完全一致。仓库源为14,933字节，SHA-256 `2e8719939a39605c285ef51813931cd6795699285641cd4b97b4e2b9dd83cdce`。

## 宿主默认模板基线

独立权威来源为QwenPaw官方GitHub仓库`v2.2.1`标签的中文工作区模板；比较统一采用“只移除唯一末尾LF”的公开API读回序列化规则：

| 文件 | 官方序列化后字节／SHA-256 | 正式专用Agent字节／SHA-256 | B臂判定 |
| --- | --- | --- | --- |
| `AGENTS.md` | 2,477／`84340929b9aa5df7fa52a4b0f10fd244491a4f206b7fdb5cccf59770f50a6fc7` | 2,552／`578419aa9fbbad40c2c6003b9d7c12e3937ba4ea506ba2126d7483275ca5f91d` | 不匹配，保留 |
| `SOUL.md` | 1,597／`6da1cb358b16ae88214b6cbbfb478d7b5b1abc0ff40306a8053fee5094433489` | 完全一致 | 可从清单排除，不删除文件 |
| `PROFILE.md` | 644／`3b40f9b7c03403164ec55dba589010482a135f7c0a42b326a92be11823966b75` | 完全一致 | 可从清单排除，不删除文件 |

官方来源：[AGENTS.md](https://github.com/agentscope-ai/QwenPaw/blob/v2.2.1/src/qwenpaw/agents/md_files/zh/AGENTS.md)、[SOUL.md](https://github.com/agentscope-ai/QwenPaw/blob/v2.2.1/src/qwenpaw/agents/md_files/zh/SOUL.md)、[PROFILE.md](https://github.com/agentscope-ai/QwenPaw/blob/v2.2.1/src/qwenpaw/agents/md_files/zh/PROFILE.md)。现行`default` Agent的对应哈希与专用Agent一致，只作交叉印证。R0B无需执行，也不会创建一次性Agent。

## 创作样本

- 作品：《末日：我把危楼建成地下堡垒》；ID `13ae3ee9-c439-473a-bf18-4e5f4a1a0e81`。
- 章节：《向下之前，先留退路》；文档ID `0cc2916b-4710-47fc-a8b0-d063e29ef7a7`。
- manifest ETag：`5aad76ae5fe2ff0e0961e74b5b816d1181a846af688810ca9548e62ddb428c31`。
- document version：2；draft version：3；base revision ID：`d31d64f6-f17a-4995-85f2-aa614bb0cf1c`。
- 正文SHA-256：`02c1d427f98de775f30965cd2e366ae6afc5c16fe65b5a344805a50c5e8dfa09`；可见字符：2,555。
- 场景切片：正文按空行分段后的第20—30段（零基索引19:30），连续11段、832个可见字符；保留段间空行后的字节SHA-256为`8c747f8c7cdf19773977403df89381a5a76ea70869a3ffe954767f9dc995f3e4`。
- 首锚点：无电排水方案开始；尾锚点：第一段永久支护完成、逃生包就位。审计不复制作者正文。

## 调用与停止合同

- A臂：现行专用prompt＋四文件清单。
- B臂：精简专用prompt＋`AGENTS.md`、`AI_NOVEL_WORLD.md`清单。
- 两臂分别执行`C1-CREATIVE`与`C2-SAFETY`，每个案例只调用一次，总硬上限4次；不自动重试。
- 分块顺序由评测器在建立私密快照后随机确定，揭盲前不写入公开审计；输出对作者显示为X／Y。
- 调用前必须重新核对本页全部正式不变量；任一漂移、健康异常、传输未知、越权写入或恢复材料不可用立即停止。
- 任何顺序结束后先恢复A并读回；正式作品、revision、候选和故事事实始终只读。
