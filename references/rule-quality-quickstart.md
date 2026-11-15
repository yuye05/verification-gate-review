# 规则体检：接入自己的模型与案例

规则体检比较“独立需求案例的预期判定”与“待测 JSON 模型的实际判定”。适合已能描述有限状态和记录顺序轨迹的开发者。它不是自然语言规则审稿器，也不自动证明测试充分。

## 1. 先确认需求，再写案例

先写清楚什么必须允许、什么必须拒绝、什么尚未完成，再给案例标注 PASS、FAIL 或 INCONCLUSIVE。预期依据不要从待测模型的输出倒推；尽量由需求所有者或独立审阅者确认。

至少准备一个预期 PASS 和一个预期 FAIL 案例。补充不同合法做法，避免只接受你最先想到的一条路径。

完整的实际执行案例见[编程工作流演示](../examples/agent_rule_quality/README.md)。以下是更小的文件接入练习。

## 2. 保存模型和独立案例

把模型保存为 `model.json`，使用现有模型格式：

```json
{
  "variables": {"checked": [false, true], "delivered": [false, true]},
  "initial": {"checked": false, "delivered": false},
  "transitions": [
    {"id": "check", "guard": {"delivered": false}, "set": {"checked": true}},
    {"id": "deliver", "guard": {"checked": true, "delivered": false}, "set": {"delivered": true}}
  ],
  "invariants": [
    {"id": "delivery_requires_check", "requirement": "REQ-DEMO-001", "when": {"delivered": true}, "assert": {"checked": true}}
  ],
  "terminals": [{"delivered": true}]
}
```

把案例保存为 `suite.json`：

```json
{
  "schema_version": 1,
  "cases": [
    {
      "id": "checked_delivery",
      "requirement": "REQ-DEMO-001",
      "rationale": "独立需求要求先检查再交付，这个流程满足要求",
      "expected": "PASS",
      "trace": {"steps": [
        {"action": "check", "before": {"checked": false, "delivered": false}, "after": {"checked": true, "delivered": false}},
        {"action": "deliver", "before": {"checked": true, "delivered": false}, "after": {"checked": true, "delivered": true}}
      ]}
    },
    {
      "id": "unchecked_delivery",
      "requirement": "REQ-DEMO-001",
      "rationale": "未检查就交付违反独立需求",
      "expected": "FAIL",
      "trace": {"steps": [
        {"action": "deliver", "before": {"checked": false, "delivered": false}, "after": {"checked": false, "delivered": true}}
      ]}
    }
  ]
}
```

这两条练习轨迹是人工编写的逻辑案例，不是程序实跑证据。接入真实程序时要独立采集状态，并核对是否遗漏动作或环境变化。

## 3. 执行体检

使用 README 安装步骤中的 Python，按文件实际位置修改路径：

```text
python -X utf8 scripts/check_rule_quality.py --model model.json --suite suite.json
```

本练习应返回 `0`，模型 PASS，案例匹配 2/2。每个负例的实际 FAIL 属于符合预期，不会让整套体检失败。

所有 CLI 路径相对于当前工作目录，脚本可用绝对路径运行。可选参数：

```text
python -X utf8 scripts/check_rule_quality.py --model model.json --suite suite.json --outdir "my reports" --max-states 10000
```

默认输出为案例集旁的 `reports/rule-quality/run-<唯一编号>/`；每次新建子目录，保留输入快照、JSON 和 Markdown 报告。SHA-256 标识本次输入，不证明标签或日志来源可信。终端打印报告绝对路径；错误时不使用旧报告。

## 4. 解读结果

| 预期 | 实际 | 分类 |
|---|---|---|
| PASS | FAIL | 误拦 false_rejection |
| FAIL | PASS | 漏检 false_acceptance |
| 相同，包括 INCONCLUSIVE | 相同 | 符合预期 matched |
| 其他不相同组合 | — | 其他判定不一致 other_mismatch |

`report.json` 独立保存 `model_check` 与 `case_verdict`；`confusion_matrix` 的行是预期、列是实际。`summary` 只计提供的案例，不是总体错误概率或经过校准的可靠性评分。

案例的 `case_requirement` 和检查器返回的 `trace_check.requirement` 含义不同：前者说明标注依据，后者只在实际不变量违规有编号时存在。守卫不满足不能凭空获得需求编号；漏检通常没有检查器违规步骤，工具不会伪造原因。

轨迹报告的 `execution_prefix` 是首次违规前缀，未经缩减，不能称为最短反例或因果根因。模型 BFS 的反例另存于 `model_check`。

### 总体判定与退出码

| 结果 | 条件 | 退出码 |
|---|---|---|
| PASS | 模型完成且通过、所有案例一致、正负例齐全 | 0 |
| FAIL | 模型违规或至少一个案例不一致 | 1 |
| INCONCLUSIVE | 无已知失败，但模型搜索未完成或正负例不足 | 1 |
| ERROR | 输入、读取、输出或运行错误，优先于已发现的问题 | 2 |

预期 INCONCLUSIVE 的合法前缀与实际一致可以计为匹配，但它不替代正负例覆盖。不可达动作或未触发属性仅提示复核；模型搜索未完成时，不作永远不可达的判断。

错误打印到 stderr，不产生成功报告；写入错误可能保留本次不完整目录。检查进程退出码，并只使用本次完整生成的报告。

## 5. 输入约束与边界

- 首版只接受现有 JSON 有限模型；没有外部 Python 插件、LLM 或网络调用。
- 案例集只含 `schema_version=1` 和非空 `cases`；每例只含唯一非空 `id`、非空 `requirement/rationale`、三值 `expected` 和 `trace`。
- 轨迹字段沿用[配置说明](configuration.md#执行轨迹检查)。完整状态、值类型、初始状态和连续性必须正确；空轨迹、域外值或断裂记录属于输入错误，不能当业务负例。
- 未声明动作、守卫、赋值或不变量不匹配仍是待测模型的行为判定，可用于暴露规则缺漏或不合理限制。
- 相同轨迹不能有冲突标签。只有正例、只有负例或只有未完成案例均不足以总体 PASS。
- 首版不生成案例、不自动修正规则，也不评估规则冗余。两条规则重复保护时，删掉一条仍拦住错误不能证明它无用。
- 合法变体和负例标注仍需外部依据；只用同一模型产生轨迹与标签会形成自证。通过不意味着所有合法路径都被允许、所有违规都能检出。

Python 调用方可将 `scripts` 加入模块路径后使用 `check_rule_quality(model, suite, max_states=10000)`。它是无文件副作用的函数，输入错误抛 `ValueError`；文件读写只在 CLI／`run_check` 层发生。
