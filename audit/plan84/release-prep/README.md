# 计划84正式发布前置

记录时间：2026-09-14 23:03–23:06 CST

状态：`ROLLED_BACK`（第四版与第七版均未通过正式URL门禁；两次都已使用同一恢复点回装上一已安装包，正式环境当前不是计划84候选）

2026-09-15拆分候选另行建立独立恢复点并完成一次正式安装；该次因草稿浏览器绑定前置不成立而停止并回退，见[首次正式尝试](../formal-split-attempt-20260915/README.md)。本文件以下内容继续保留第四版与第七版的历史回执，不倒改当时基线。

## 发布对象与候选身份

- 正式容器：`ai-novel-2026-qwenpaw-lab`，健康且镜像为`ai-novel-2026-qwenpaw-runtime:2.2.1-mvp0`。
- QwenPaw：2.2.1；PawApp：`ai-novel-world-2026` 0.4.0，发布方式为公开CLI `plugin install --force`原位热更新。
- 第七版候选生产源码哈希：`1c0c53d4df77e27b08308729d2e896fd58d2a7c0238041d670ece6cb4037ef90`。
- 第七版候选正式打包树哈希：`42226a0e8202aaf08e77cbc9f524efda164637724eca82b40757aeb009232dfa`。
- 第七版候选bundle：`0f1c730f3ddf130971e22cb2b479d67bf5ca5d213fc905dbbb47624ec795bc6c`；manifest：`79fae92a55706815babcd349bae892f70f680cd8d4f3abdcc363210bcec18605`。
- 只有第七版P84-QA通过且正式基线复核无漂移后才允许再次热更新；第四版身份只保留在下方“首次发布与回退回执”历史中，不得用于当前发布。
- 数据库head：`20260913_0056`；本计划无迁移。

## 精确恢复点

- 短期恢复目录：`/private/tmp/plan84-release-axbqjO`。
- 上一已安装插件树：`plugin-before/`；项目正式树哈希为`4e253b9712356138a8f615cc7b36c3c828e1706e2dbd919cce9e1249d84d88ec`。
- 归档：`plugin-before.tar.gz`，SHA-256为`c632d1fa2d74c7ba4c62b18a809e97f87e951d14153ef4d7d66a3a4fd396a56b`。
- 目录另含公开Skill状态、Agent选择、工具开关、prompt文件及清单、插件状态、容器状态、健康响应、数据计数、目标私有库版本和计划84草稿状态；不含密钥或正文。
- `ROLLBACK.md`已写明公开路径恢复命令；QwenPaw CLI已读回确认运行中安装会热加载，无需重启。

## 发布前正式状态

- Agent `ai-novel-writer`：`bigmodel/glm-5.3-flash`，运行中。
- system prompt清单：`AGENTS.md`、`SOUL.md`、`PROFILE.md`、`AI_NOVEL_WORLD.md`；四文件SHA-256已单独保存。
- 项目Skill：12/12启用；工具：35项可见、33项启用，仅`append_file`与`delegate_external_agent`停用。
- 作品：公开列表5本，数据库根行6行；建书草稿6份；私有资产16份、内容版本41份。
- 唯一计划84草稿：`c150ebf2-a5a9-400a-ae33-9b96c6f59e21`，`draft`，version 3，step 1，未完成为作品。
- 两份目标词汇资产仍为根CAS/内容版本4/4与2/2；非词汇抽查资产`cb1c0964-f8b8-46cb-9a54-2e4d63697ff6`为2/2，完整内容163字节，SHA-256为`8523a496b2c6ab86b071e702d49f9517397a0c133f2d48470bae5e4d2ecd3a0d`。

## 中止和恢复

任一健康异常、URL循环／普通聊天被侵占、Agent／Skill／工具／prompt漂移、除唯一草稿的一次预期保存外发生数据变化、私有库版本变化或新增PawApp浏览器错误，立即中止。恢复时使用恢复目录中的`plugin-before`通过同一公开CLI回装，再读回对比全部基线；不删卷、不卸载、不直接改表。

## 首次发布与回退回执

- 23:09通过公开CLI热更新第四版候选；12项Skill原样恢复，容器未重启。
- 通用验证器首次未显式传入正式TTS `ready`期望而失败；按正式环境参数重跑后完整通过，该项为验证器调用参数问题，不是产品健康失败。
- 已安装生产文件在排除QwenPaw运行生成的`__pycache__`后与第四版候选树精确一致。
- 真实Edge冷加载仍观测到官方入口最终落在无`novel_center=1`的裸会话，且直接根规范URL同样失败；候选样式已在浏览器中出现，因此不是旧bundle缓存。
- 按冻结中止条件回装`plugin-before`并恢复Skill；正式健康、模型、Skill作用域、工具和prompt清单验证通过，容器启动时间未变。

## 第七版发布与回退回执

- 23:39发布前再次确认候选树`42226a0e…`、恢复点、容器健康、数据库计数6/6/16/41、唯一草稿version 3及正式TTS ready期望；均无漂移。
- 通过公开CLI热更新第七版；12项Skill原样恢复，无补偿、无容器重启。已安装目录排除QwenPaw运行生成的`__pycache__`后与冻结包逐文件一致，正式验证器通过。
- 真实Edge 1920×1080从官方`/apps/ai-novel-world-2026`冷加载，最终URL仍为无参数`/chat/b9c0bbb4-ff55-4ad5-bbae-a092028b1302`，可访问树显示原生聊天而非创作中心。原始浏览器日志和截图当时未归档；结合该现象与QwenPaw 2.2.1公开的动态加载生命周期、无首轮前注册／路由重放API，工程上推断插件组件没有及时取得写入pending权限。
- 立即停止后续私有库、设定、弹窗和布局正式验收，并按公开CLI回装`plugin-before`、恢复Skill。正式验证器、容器健康与启动时间、数据库计数6/6/16/41、唯一草稿ID/state/version均与发布前一致；没有执行模型、音频、embedding或作品／私有库写入。
- 回退归档历史哈希包含当时运行生成的`__pycache__`。回退后缓存会重新生成，不能逐字节复现缓存哈希；排除`__pycache__`与`*.pyc`后，当前已安装生产文件与`plugin-before`逐文件完全一致，清洁树哈希为`37c0f3e11972e0b718ece1e04658bbb2e9401be1cda7deea2fe21d77a0dd7f32`。
