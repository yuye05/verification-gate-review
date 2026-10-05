# 贡献指南

欢迎通过 [Issues](https://github.com/yuye05/verification-gate-review/issues) 报告问题或提出改进，或提交 Pull Request。

## 开发与验证

```bash
git clone https://github.com/yuye05/verification-gate-review.git
cd verification-gate-review
python -m pip install -r requirements.txt
python -X utf8 evals/check_regressions.py
```

当前已在 Windows / Python 3.13 验证。光学与订单示例的运行命令见 [README](README.md#验证与开发) 和[设计说明](references/design-notes.md#验证方式)。

## 问题反馈

请提供最小复现步骤、Python/依赖版本、相关配置、预期结果与实际结果。
负对照返回 FAIL/退出码 1 是预期行为；报告中如有私人路径、业务数据或密钥，请先脱敏。

## Pull Request

1. 从 `main` 创建分支，一次处理一个明确问题。
2. 保留三层门禁和配置驱动接口；行为变化须更新对应说明及回归检查。
3. 运行回归入口并检查 `git diff --check`，说明改变的行为、理由和验证结果。
4. 记录到 [CHANGELOG.md](CHANGELOG.md) 的 Unreleased 部分。
5. 不提交缓存、虚拟环境、运行报告、本机路径快照或敏感输入。

## 贡献权利与辅助工具

有意提交并纳入本项目的贡献按 [MIT License](LICENSE) 提供，除非双方另有明确约定。
提交者需拥有相应权利；使用第三方材料时说明来源、许可，并保留必要声明，确保可按项目许可分发。

允许使用 AI 辅助工具。提交者仍需审阅代码、核实来源并验证行为；较大改动在 PR 中简述辅助工具与人工设计、审阅及验收工作。
请勿把未经审查的生成输出作为已验证成果提交。
