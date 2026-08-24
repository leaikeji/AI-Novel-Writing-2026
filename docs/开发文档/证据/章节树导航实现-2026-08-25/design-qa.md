# 章节树导航 Design QA

日期：2026-08-25
范围：章节写作页左侧“卷—章节”树导航，桌面端。

## 比较目标

- 源视觉真相：`/Users/liujia/.codex/generated_images/01a02cfd-0d33-7bd3-9bd5-1f7b7f6b0a67/exec-53502aeb-b217-4985-bd22-6cfab091473b.png`
- 浏览器实现（同尺寸）：`/Users/liujia/Documents/AI小说世界2026/docs/开发文档/证据/章节树导航实现-2026-08-25/implementation-final-1498x1050.jpg`
- 浏览器实现（验收尺寸）：`/Users/liujia/Documents/AI小说世界2026/docs/开发文档/证据/章节树导航实现-2026-08-25/implementation-final-1920x1080.jpg`
- 收起状态：`/Users/liujia/Documents/AI小说世界2026/docs/开发文档/证据/章节树导航实现-2026-08-25/implementation-collapsed-1920x1080.jpg`
- 全图同图比较：`/Users/liujia/Documents/AI小说世界2026/docs/开发文档/证据/章节树导航实现-2026-08-25/final-source-vs-implementation-1498x1050.jpg`
- 目录聚焦比较：`/Users/liujia/Documents/AI小说世界2026/docs/开发文档/证据/章节树导航实现-2026-08-25/final-focused-tree-comparison.jpg`

## 视口与归一化

- 源图像素：1498×1050。
- 同尺寸实现截图：1498×1050 CSS px，截图 1498×1050，devicePixelRatio 1；无缩放归一化。
- 桌面验收截图：1920×1080 CSS px，截图 1920×1080，devicePixelRatio 1。
- 状态：章节目录展开、两卷展开、当前为第4章、搜索关闭；亮色主题、真实登录态和真实小说数据。

## 交互验证

- 搜索按钮展开输入框；输入“雾里”后只保留第二卷和“第5章 雾里来的人”。
- 第一卷可折叠，第二卷和当前章状态保持不变。
- 点击第5章后 URL、正文标题和目录高亮同步切换；随后成功返回第4章。
- 总目录可折叠为窄栏，恢复按钮使用双右箭头；展开按钮使用双左箭头。
- 跳转前会取消旧的延时保存任务；存在未保存正文时等待保存成功再加载目标章节。
- 浏览器控制台 `error`/`warn`：0。

## 必查保真面

- 字体与排版：沿用项目 Inter/系统中文字体回退；目录标题、卷标题、章节名、字数四级层次与源图一致，长标题使用省略号。
- 间距与布局：目录独立 256px 可视宽度；顶部栏和正文纸张在剩余空间中保持同轴，1920×1080 下纸张仍为 1000px。
- 颜色与令牌：复用项目橙色令牌；当前章使用 `#fff0e9` 浅橙底和橙色左标，其他行保持白/浅灰层次。
- 图片与资产：本功能无内容图片；搜索、折叠、展开和卷箭头均使用宿主 Ant Design 图标库，无自制 SVG、CSS 图形或占位图。
- 文案与内容：固定文案为“章节目录”“搜索章节”“折叠章节目录”“展开章节目录”；卷章名称和字数来自真实作品数据。
- 可访问性：目录为 `aside`＋`nav`；卷和章节均为原生按钮；展开状态使用 `aria-expanded`，当前章使用 `aria-current=page`，搜索和折叠按钮均有明确 `aria-label`。

## 比较历史

1. 第一轮实现使用 `MenuFoldOutlined/MenuUnfoldOutlined`。聚焦对比发现图标更接近“菜单收起”，与用户批准的双箭头视觉存在 [P2] 图标语义和形态偏差。
2. 修复为 `DoubleLeftOutlined/DoubleRightOutlined`，重新构建、部署并捕获同尺寸和 1920×1080 浏览器证据。
3. 最终同图比较未发现可执行的 P0/P1/P2 差异。真实小说的章节名、字数与生成稿示例不同属于预期动态内容；实现额外显示每卷章数，归类为可接受 P3 信息增强。

## Findings

- 无未解决的 P0/P1/P2。

## Follow-up Polish

- [P3] 如后续希望绝对贴合源图，可隐藏卷右侧“3章”；当前保留能帮助长篇作者快速判断卷规模。

final result: passed
