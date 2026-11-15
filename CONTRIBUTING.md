# 贡献指南

欢迎通过 [Issues](https://github.com/yuye05/verification-gate-review/issues) 报告问题或提出改进，或提交 Pull Request。

## 开发与验证

```bash
git clone https://github.com/yuye05/verification-gate-review.git
cd verification-gate-review
python -m pip install -r requirements.txt
python -X utf8 evals/check_regressions.py
python -X utf8 evals/check_demo.py
python -X utf8 evals/check_rule_quality.py
python -X utf8 examples/microservice_order/run_demo.py
python -X utf8 examples/agent_rule_quality/run_demo.py
```

请先按 [README](README.md#快速开始)创建独立虚拟环境；上面的 `python` 指该环境解释器，不需要激活环境。
当前已在 Windows / Python 3.13 验证。86 项核心回归与 6 项演示端到端测试分开计数；演示测试会在独立副本中注入错误，不改动原例子。
规则体检另有 14 项测试。修改该功能时请同时核对误拦、漏检、INCONCLUSIVE 与输入错误；故意注入的测试故障不能被算作真实 Agent 故障。
Windows/Ubuntu 的 GitHub Actions 工作流已配置，远端执行结果以 Actions 页面为准；本机测试不能替代 Ubuntu/macOS 验证。
光学与分步订单命令见[进阶使用](references/advanced-usage.md)。

## 问题反馈

请提供最小复现步骤、Python/依赖版本、相关配置、预期结果与实际结果。
直接运行缺陷检查时，FAIL/退出码 1 是预期行为；`run_demo.py` 会核对两个场景，只有都符合预期才退出 0。不要把检查器崩溃或缺失报告当成检出缺陷。
报告中如有私人路径、业务数据或密钥，请先脱敏。首次使用反馈也欢迎说明卡在哪一步、是否能独立跑通、准备接入什么流程。

## Pull Request

1. 从 `main` 创建分支，一次处理一个明确问题。
2. 保留三层门禁和配置驱动接口；行为变化须更新对应说明及回归检查。
3. 运行回归入口并检查 `git diff --check`，说明改变的行为、理由和验证结果。
4. 记录到 [CHANGELOG.md](CHANGELOG.md) 的 Unreleased 部分。
5. 不提交缓存、虚拟环境、运行报告、本机路径快照或敏感输入。

规则体检的案例预期须有独立需求依据，至少包含合法与违规案例；不能根据待测模型结果反向修改标签使其通过。接入方式见[规则体检教程](references/rule-quality-quickstart.md)。

## 贡献权利与辅助工具

有意提交并纳入本项目的贡献按 [MIT License](LICENSE) 提供，除非双方另有明确约定。
提交者需拥有相应权利；使用第三方材料时说明来源、许可，并保留必要声明，确保可按项目许可分发。

允许使用 AI 辅助工具。提交者仍需审阅代码、核实来源并验证行为；较大改动在 PR 中简述辅助工具与人工设计、审阅及验收工作。
请勿把未经审查的生成输出作为已验证成果提交。
