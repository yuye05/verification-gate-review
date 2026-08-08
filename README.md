# verification-gate-review

交付数字结果 / 算法结论 / 文档口径前，用机器可复现的 PASS/FAIL 报告替代口头承诺"没问题了"。

## 它解决什么问题

数据审查最怕三种漏：数字算错了、旧口径残留了、算法有系统偏差。靠人眼/记忆核对容易漏。
本 skill 用三个机器可复现的检查替代人眼核对，报告说 PASS 才算 PASS。

## 三步门禁

| 步骤 | 脚本 | 作用 |
|---|---|---|
| ① 一致性门禁 | `check_consistency.py` | 从权威 JSON 提取全部数字当"真值"，扫描文档/图注，查旧口径残留(FAIL)、核心数字缺失(WARN)、孤儿数字候选 |
| ② 合成自检 | `synthetic_check.py` | 用已知答案的合成数据跑被测算法，验证还原误差 < 阈值，证明算法无系统偏差 |
| ③ 对抗性审查 | 手动整理 | 预判评审/队友最可能质疑的点，逐一写答辩 |

## 快速开始

```bash
pip install -r requirements.txt

# 1. 按 references/gate_config.example.json 创建本项目 gate_config.json
# 2. 跑一致性门禁
python scripts/check_consistency.py --config gate_config.json
# 3. 跑合成自检（可选：配置了算法段才跑）
python scripts/synthetic_check.py --config gate_config.json
```

## 配置说明

`gate_config.json` 是唯一的配置入口，字段说明见 [references/gate_config.example.json](references/gate_config.example.json) 的 `_doc` 段：

- `authoritative_json`：权威数字来源 JSON（真值）
- `scan_dirs`：要扫描的文档/代码/图注目录
- `forbidden_numbers` / `forbidden_texts`：已废除的旧口径，出现即 FAIL
- `whitelist`：合法但非结果的数字（物理常数/参数/DOI），孤儿检测跳过
- `core_docs` / `core_key_fragments`：核心结果必须出现的位置

## 输出

| 文件 | 内容 |
|---|---|
| `门禁报告_一致性.md` | 数字口径差异清单（FAIL/WARN/候选） |
| `门禁报告_合成自检.json` | 合成数据还原误差与 PASS/FAIL 判定 |
| `对抗性审查清单.md` | 预判质疑 + 答辩要点 |

## 使用方式（作为 Claude Code skill）

本仓库同时是一个 Claude Code skill。放入 `~/.claude/skills/verification-gate-review/` 后，在交付前说"跑门禁"即可触发。

**⚠️ 手动触发**：仅在用户明确要求时使用，不因对话中出现"检查/验证/审查"等词自动触发。

## 许可证

MIT
