# VC43-ROLLBACK — 插件生命周期与旧包回退

状态：**PASS**

日期：2026-08-31（Asia/Shanghai）

- 候选包目录树 SHA-256：`72471c8a8f31affb4fa0f923f4b9f91a2edead9da48e0d2575874038405bdde6`。
- 候选前端资产 SHA-256：`a4acba9c7fd5894b18d0de7cea3072d1825a7bf3a686542cb99cb98e420852a3`。
- 长期已安装旧前端资产 SHA-256：`4348a62a5507a3a8a39f47a073c6ecba18dae6980cc536f1b99b25c0a5d07d4a`；它与候选包不同，证明长期环境未被本次候选覆盖。
- 从长期安装目录制作的只读临时旧包聚合 SHA-256：`3bace8b7426ba4d3e03e36479c6bfda79965eb60ad33b7ae20942eeb4aa872ff`。
- 隔离 QwenPaw 执行：候选安装 → 公开 API 卸载 → 原生聊天恢复且 PawApp health 404 → 候选重装且数据保留。
- 回退演练执行：强制安装旧包，health／DB／原生 chat 通过且资产哈希匹配 `4348…`；再安装候选包，health／DB／chat 通过，资产哈希匹配 `a4ac…`，迁移 head 为 `0035`。
- 临时旧包副本已移入 macOS 废纸篓，可恢复；隔离容器与数据卷是纯合成验收数据，验收后已精确删除，运行态不可恢复。
