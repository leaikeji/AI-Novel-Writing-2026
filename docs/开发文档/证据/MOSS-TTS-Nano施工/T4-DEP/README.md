# T4-DEP：正式编辑器依赖冻结

状态：**`PASS_DEPENDENCY_ONLY_WITH_T4_F_AND_T4_GATE_HOST_HOLDS`（2026-08-27）。根项目仅接入 CodeMirror 6 的最小三项直接依赖；依赖锁、许可证、类型检查、单 ESM 和零 bundle 漂移已通过。CodeMirror 尚未挂载到产品页面，固定 QwenPaw 的 Blob/CSP、系统中文 IME、正文保存链、textarea 回退与真实浏览器仍保持 HOLD，必须由 T4-F 和 T4-GATE 关闭。**

## 1. 范围与裁决

T4-DEP 持有 `LOCK-DEPENDENCIES`，只允许修改根 `package.json` 和 `pnpm-lock.yaml`。本工作包不接线编辑器、不改页面、不新增数据库、不运行 TTS，也不翻转任何产品 capability。

直接依赖固定为：

| 包 | 版本 | 许可证 | 用途 |
| --- | --- | --- | --- |
| `@codemirror/commands` | `6.11.0` | MIT | history、undo/redo 与公开命令 |
| `@codemirror/state` | `6.7.1` | MIT | UTF-16 文档、transaction、effect/state field |
| `@codemirror/view` | `6.43.9` | MIT | EditorView、decoration、gutter、update listener |

明确不接入：

- `@codemirror/lang-markdown`：当前冻结功能不需要 Markdown parser；
- `@codemirror/language`：由 `commands` 以固定 lock 传递引入，不作为根直接依赖；
- Monaco、ONNX Runtime Web、jsdom：均属于阶段 0 对照或测试环境，不进入正式根运行时。

锁文件新增 11 个运行时包，全部核验为 MIT：CodeMirror commands/language/state/view、Lezer common/highlight/lr、`@marijn/find-cluster-break`、`crelt`、`style-mod`、`w3c-keyname`。未出现既有依赖重解析或无关 lock churn。

## 2. Bundle 基线与预算

以 T3-GATE 后当前正式源码为锚：

| 指标 | T4-DEP 前 | T4-DEP 后 | 增量 |
| --- | ---: | ---: | ---: |
| `frontend/dist/index.js` raw | 2,228,813 B | 2,228,813 B | 0 B |
| zlib level-6 gzip | 768,451 B | 768,451 B | 0 B |
| JS chunk | 1 | 1 | 0 |
| external imports | 0 | 0 | 0 |
| dynamic imports | 0 | 0 | 0 |

T4-F 正式接线后相对上述锚点冻结硬预算：

- 增量不超过 400,000 B raw / 115,000 B gzip；
- 总量不超过 2,628,813 B raw / 883,451 B gzip；
- 超出必须重审，不能通过追加 Markdown、Monaco 或 ONNX 依赖解决。

阶段 0 完整编辑器桥 `write:false` 探针的参考增量为 360,018 B raw / 101,396 B gzip，单一 ESM，`imports=[]`、`dynamicImports=[]`。

## 3. 实际验证

使用项目固定 Node 24.19.0 与 pnpm 11.19.0：

```text
pnpm install --lockfile-only                   PASS
pnpm install --frozen-lockfile                 PASS；新增 11 个包，全部复用本地 store
pnpm typecheck                                 PASS
pnpm build                                     PASS；73 modules transformed
Vite write:false output                        1 JS chunk；imports=[]；dynamicImports=[]
node --check frontend/dist/index.js            PASS
bundle contains module.exports                 false
git diff --check（package/lock/ADR）            PASS
```

依赖落地后的源文件 SHA-256：

```text
10f076b1bd53bb16ef95dfdde0f587281e713edee258f4a95dcb063cd4fe18bb  package.json
74022bc5be805b88c808d35bd407304c8434eeb1ab103ce72593492a3ce6955e  pnpm-lock.yaml
```

## 4. 尚未通过与回退

`style-mod` 会在运行时注入 `<style>`；阶段 0 的隔离 Blob 结果不能替代固定 QwenPaw CSP 实测。因此以下内容继续 HOLD：

- 固定 QwenPaw 完整 PawApp bundle 的 Blob/CSP 加载；
- 系统中文 IME、长章输入、selection、undo/redo；
- 600 ms debounce、保存中追保存、CAS 409、IndexedDB recovery、AI apply/undo 和章节 generation fencing；
- CodeMirror 挂载失败时 textarea 的真实降级；
- 1920×1080 与 2560×1440 的页面布局、键盘、焦点和 ARIA。

若 T4-F 或固定宿主门禁失败，保持 `editor_production_enabled=false`，继续使用既有 textarea，并移除 CodeMirror 接线和这三项根依赖即可回退；不涉及数据库、正文或历史 revision 迁移。低于 1920×1080、移动窄屏和 200% 等效小视口按用户最新裁决为非目标、非阻断。
