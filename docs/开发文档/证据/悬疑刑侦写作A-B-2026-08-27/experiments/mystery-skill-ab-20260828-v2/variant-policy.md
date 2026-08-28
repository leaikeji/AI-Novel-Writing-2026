# V2 Skill 版本对照策略

状态：冻结候选；两侧题面、可信封套、最终输出约束、目标模型和生成参数必须相同。

- A 侧安装基线 `prose-writing`，SHA-256 为 `cbf113c0a2b71cda1f54ca029d98ee9263323c21db75cd76539bffb0867d72e2`。
- B 侧安装候选 `prose-writing`，SHA-256 为 `1139c7bea46a7781c17ba55fb8543ec2d5f6aa42a65f1f4f960354d1c76317a2`。
- A/B 不再使用不同提示覆盖层；同一 case、同一 attempt 的 prompt 必须逐字节相同。
- 每次生成前由研究 API 读取当前 PawApp 包内 `skills/prose-writing/SKILL.md` 的公开项目文件哈希；与该样本登记版本不符时，在调用模型前拒绝。
- 基线原文保存在 `baseline/prose-writing.SKILL.md`。候选原文以仓库 `skills/prose-writing/SKILL.md` 及上述哈希冻结。
- `scene-craft` 候选 SHA-256 为 `49832573e8316d918b99ec2cb4710a47ca2481b7f95ded4fbf2c83836e623a34`；X01/X14 只显式调用 `prose-writing`，因此这对哨兵不把 `scene-craft` 的质量变化写成已验证。
- Skill 包切换、QwenPaw 重启和真实生成必须串行。每侧只调用一次，不自动重试；任一侧输出污染、哈希不符或运行态恢复失败即停止。

V2 哨兵只验证版本隔离、原始输出纯净度和 SP-02 场景的已知缺陷是否改善；不能替代完整 12 任务、双生成、匿名盲评，也不能单独证明总体写作能力提升。
