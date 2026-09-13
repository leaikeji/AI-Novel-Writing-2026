# 未采用候选的桌面与恢复验证

日期：2026-09-13 22:40（Asia/Shanghai）。正式源仍为15f4f5f；本轮没有代码部署、重启、迁移或模型配置变更。状态：候选交互与恢复分项PASS，完整2K截图受限，R5继续开放。

## 真实写作动作与保护

- 作品《缺氧：末日地下世界》，第二章《第一道裂缝》。原稿已经写到量湿痕，却没有明确可复查的边界，而且把明沟干燥过早解释为墙内渗水来源。本轮只在“本章期待”补充观察起止点、复测方法和证据边界，不改变情节、大纲、字数、角色或禁止事项。章纲v3→v4；[原章纲](preview-brief-before.json)和[修订后章纲](preview-brief-after.json)逐字段比较仅version、expectation_text、updated_at不同。
- 页面正常发起一次正文生成，随后切到第一章，避免旧页面回调自动续接采用；没有取消服务端任务或另开生成。任务`a26c4144-747b-4fdf-851e-7e32d481e367`于22:24:31开始、22:29:48完成，attempt1，模型执行证据duration_ms=316987。前后任务列表仅新增这一个正文job，见[之前](preview-jobs-before.json)与[之后](preview-jobs-after.json)。不据此断言方法判断完全没有独立模型调用。
- 候选`ccb7e0f4-4f55-4ec0-b7f8-ede480cee61f`，2668字，hash `c837e8b5eeeb632d8cfe5288520b3fe12f5cd17c605c43d291a05f061842bb5f`，最终仍为ready／未采用。原文和候选分别保留，不以生成成功冒充采用成功。
- 请求及任务前后有效模型均为bigmodel/glm-5.3-flash；actual模型与usage仍未公开。页面显示本次请求提供“小说正文写作／金手指机制写作”，不外推宿主实际Skill执行或文学效果最优。
- 候选中湿痕段改为明确四条边、明早复测，且明沟干只证明当下未见地表流淌，管道还须排查。现金423、点数0、人物与滴水结尾保留。不过“从配电柜上撕回来的检修签到表”、用湿痕自身上缘作为复测边界等仍值得作者审阅；这是有用的修订候选，不是全文质量通过或建议立即整章替换。

## 报告、逐项决定和刷新

[最终报告](preview-report-after.json)`3ebc82d3-fee4-4d98-9cce-0070c3d08362`：complete、v2、两处命中、rules hash `66f79a729bbbe2f0116fc932ccf60775b6aa0d32282fdacf033237f83e6bded5`，仍使用本书用词固定v10，不把未绑定v12当成输入。

1. 从历史明确定位2668字、未采用的新候选，打开检查预览；两项默认不选，继续按钮禁用。没有操作旧已采用候选的历史恢复。
2. 两处“微微”均可用Enter定位到完整只读候选中的对应mark，位置369–371、877–879。未修改正文编辑器。
3. 用Space只勾选第一项，再用Enter保存决定；界面显示“尚未采用到正文”。第一项hit `df35bf16-d6a8-5807-99d8-4cc0622d4e6a`为keep_once，第二项`a0d869ce-ff2e-5a21-a800-7c2907b104bc`仍待处理，继续按钮仍禁用。
4. 正常刷新页面，再从同一候选历史打开，第一项已保存状态恢复，第二项仍未选。没有再次生成或创建revision。首次鼠标点击历史未打开，改用Enter成功；未把一次无效果点击记为完成。
5. Escape退出检查后焦点回到该候选“恢复此版本”；Escape退出历史后焦点回“历史”。小桌面以方向键滚动只读正文，scrollTop由576.73变为579.70；Shift+Tab跳过禁用按钮回“返回修改，保留候选”，Enter安全退出。

## 真实尺寸与截图限制

临时viewport设置1939×1091、2586×1455、1280×720，页面实际测得下表CSS视口；dpr约1.01。结束后reset默认尺寸并折叠助手。图片未经缩放、拼接或补边处理；文件名按`sips`实际像素纠正。

| 实际CSS视口 | 证据 | 分项结论 |
| --- | --- | --- |
| 1920×1080 | [43：1919×1080稳定截图](desktop/43-candidate-preview-1919x1080.jpg) | 完整候选面板、第一处mark、默认未选和禁用继续可见；面板交互PASS。图片差1像素如实保留。 |
| 2560×1440 | [45：2450×1440稳定截图](desktop/45-candidate-preview-settled-2450x1440.jpg)、[48：原生同尺寸截图](desktop/48-candidate-native-2450x1440.jpg) | 候选面板完整，第二处mark在预览内，逐项恢复PASS；截图右边未覆盖全部CSS视口，不能声称完整2K全屏截图PASS。 |
| 1267×713，宿主侧栏＋章节目录＋展开助手 | [49：1267×713截图](desktop/49-candidate-small-assistant-1267x713.jpg) | 弹窗rect x273.66/y54.01/w720/h604.85在视口内；内部滚动可达全部内容，第二处mark在可见预览内，键盘返回正常。 |

2K原句mark rect x1550.37/y1031.17/w28.57/h16.34，位于预览rect x978.19/y828.62/w638.00/h220内；1080P第一处mark也位于预览内部。只读区2752字符与候选原始文本对应，可见字数按产品口径2668。没有因截到文字片段就宣称整个编辑器或宿主所有功能通过。

保留截图工具异常原件：[41](desktop/41-candidate-preview-2450x1440.jpg)、[42切尺寸旧帧](desktop/42-candidate-resize-transient-1838x1080.jpg)、[44旧帧](desktop/44-candidate-older-frame-2450x1440.jpg)、[46指定clip](desktop/46-candidate-clip-anomaly-2535x1426.jpg)、[47 fullPage](desktop/47-candidate-fullpage-anomaly-2535x1426.jpg)。后两种捕获仍有大块空白，不能用它们补齐2K门禁；未通过编辑图片伪造完整截图。

## 最终不变项和未闭合项

- [第二章完整文档](preview-document-after.json)与[操作前](preview-document-before.json)JSON完全相同：draft11、2535字、hash `52f96be8fab7f906d4bb872b16d96be40485a211ee072d1e659bde5ea764d8f2`，原revision保留。未采用的2668字候选与第一项保留决定可继续审阅。
- [第一章](preview-chapter-one-after.json)仍draft4／4394字／hash `0873af2850b92e0592295e2883133cade6e2b2831295cf7075534d6bde750d33`。切入时已有朗读显示2/210句、0:09、1.5倍；本轮没有新建、播放或改动声音资产。
- [绑定](preview-bindings-after.json)与F20末尾save-tree-bindings-after.json完全一致。没有启用新词包版本或修改通用资产。
- [当前通用库](preview-catalog-current.json)include_archived=true、limit100、total13、has_more=false；真实101+资料门禁未覆盖，不能造占位资料凑数。
- 新复核发现历史标签把unresolved计数写成“生成时检查 · 禁用表达N处”：保存第一项后历史显示1处，但持久扫描仍是2处。扫描事实没有丢失，标签却混淆当时命中与当前待处理数，记F21待修，不因预览交互PASS掩盖该问题。
- F19非complete等未正式覆盖的负向分支继续维持原证据层级；本轮只证明上述切章、已保存决定刷新、键盘退出和候选保留，不宣称所有网络／CAS矩阵已正式通过。AI维护20场景及文学A/B仍按14.8单列。
