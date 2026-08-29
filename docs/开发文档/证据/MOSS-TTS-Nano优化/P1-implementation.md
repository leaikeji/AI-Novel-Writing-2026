# P1 朗读设置、人物覆盖与章节播放器实施证据

状态：**2026-08-29 源码候选与自动化回归通过；W6 真实隔离安装连续两次在 Docker Desktop 启动新 PostgreSQL 容器前超时，候选包尚未安装。`P1-RELEASE=HOLD_ENVIRONMENT`，不使用仍运行旧包的 18088 页面伪造新 bundle 验收。**

## 1. 已实现事实

- 后端新增独立播放偏好窄 `PATCH`：只写 `playback_rate/volume`，携带 settings CAS，不覆盖旁白、语言、规则或停顿。
- 新建 Edition 冻结 `profile_id/version_id/display_name/source_type/preset_id`；旧 Edition 通过专用读取契约返回稳定 ID 与“旧版未保存名称”，不查询当前 profile 补历史。
- 播放器将 `volume` 与 `setVolume` 收紧为必需契约。WebAudio 只使用一个 `GainNode`，双 audio fallback 同步最新音量；切换 fallback 不丢失最新倍速/音量。
- 会话加载时读取作品播放偏好；恢复进度的倍速优先于作品默认，音量取作品设置。倍速与音量立即作用于播放器，250 ms 后以窄 CAS 保存；冲突时读取服务端当前值并回写播放器。
- 章节播放器移除固定 `94px` 安全区，使用真实 flex 布局；增加 `compact/expanded/failure-details`、时间/可播放/全章进度、音量、0.5–3.0 倍速、冻结音色身份及偏好保存状态。
- 朗读设置重组为六个作者入口：总览、旁白、人物配音、音色库、朗读规则、存储与隐私；旧 `casting-rules/pronunciation/audio-cache` 深链映射到新入口。
- 旁白页采用受控语言 `zh-CN/en/ja-JP`、紧凑/自然/舒缓停顿预设、折叠精确毫秒、独立播放偏好保存和默认折叠的范围覆盖。第一人称与内心独白设置保留在高级区，未因简化页面而删除语义。
- 人物页使用覆盖卡片显示已配置/未配置、当前绑定和官方/私人/不可解析来源；`VG1=NO-GO` 后接入基于人物稳定 ID 与作品语言的官方音色自动分配，单项与批量都调用现有原子直用服务，并明确说明这不是新音色生成。
- 识别与复核、发音命中合并到一个键盘可达工作区；VoiceGenerator 为 HOLD 时只显示原因，不展示伪授权或伪生成入口。

## 2. 自动化证据

```text
pnpm typecheck
PASS

pnpm test
Test Files  102 passed (102)
Tests       920 passed (920)

播放器/会话/工作台聚焦：
Test Files  9 passed (9)
Tests       100 passed (100)

设置/规则/页面聚焦：
Test Files  9 passed (9)
Tests       92 passed (92)

.venv/bin/python -m pytest
3093 passed, 138 skipped
```

## 3. 浏览器核验与未完成门禁

浏览器在 `http://127.0.0.1:18088` 使用现有测试作品可以进入朗读页，但可见页面仍为开工前已安装 bundle：它明确显示“6 个中文官方预设”、旧自由文本语言和旧毫秒表单。该事实证明长期运行环境没有被本轮施工静默覆盖，也意味着不能把当前页面截图冒充新源码的浏览器验收。

因此以下项目仍等待 Docker Desktop 恢复可启动新容器后，由 `MNX-FINAL` 的隔离安装执行：

- 新 bundle 的 1920/2560、1024、720、390 px 与 960×540 等效 200% 检查；
- 助手展开/收起、失败详情焦点恢复、键盘/IME、读屏 live 区；
- 官方 18 音色、人物覆盖表、新设置页与播放器对正文不遮挡的任务式验收。

不为完成截图而更新唯一长期 QwenPaw、长期数据库或其安装 bundle。

W6 两次 real 隔离生命周期验证使用当时候选包 tree SHA-256 `e87a83ac6eddbdfd0624c0c8cf84592dd79f941ea0e953940c22b8d3668d3d76`，都在 `start-postgres` 阶段超时；诊断容器为 `created`、无日志、无 OOM/地址冲突/数据库错误，后续最小 `docker create` + `docker start` 同样卡在 Docker Engine start API。两次验证器和最小诊断均已精确删除其容器、卷与网络，没有使用广域 prune。最终自审修正后重打包的 tree SHA-256 为 `9b32c18a08e3f688f6636eb1918e1658fc93a3dcc58bc164a09c3d8eee221aa7`，dry-run 中的候选哈希、四次公开安装/卸载操作、无端口/无 bind mount 拓扑和精确清理契约均通过。最终包未再运行 real lifecycle，因为最小 Docker start 诊断已确认同一环境阻断。

## 4. 结论

`P1-CODE-GATE=PASS`，`P1-AUTOMATION-GATE=PASS`，`P1-BROWSER-GATE=HOLD_ENVIRONMENT`。P1 源码契约可作为后续候选的稳定前置，但在隔离安装浏览器矩阵通过前不写成 `P1-RELEASE`。
