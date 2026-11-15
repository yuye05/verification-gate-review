# 编程工作流的规则体检演示

规则自身能否忠实表达需求？本例对同一批执行轨迹应用三套规则，展示误拦与漏检。

## 独立需求与标签依据

以下需求先于待测规则定义。标签固定在 [cases.json](cases.json)，采集程序只执行动作并记录观察结果，不从模型生成预期答案。

- **REQ-DELIVERY-001：**本例把 `subject.py` 与固定 `test_subject.py` 的全部字节作为验证范围。仅当当前这两份文件对应的最近一次指定测试确实执行且通过，才允许按已验证交付。任一文件变化需要重测；历史通过不能覆盖当前未测或失败状态。
- **REQ-DELIVERY-002：**只读查看差异不会改变受测文件，不使测试结果失效。
- **REQ-DELIVERY-003：**只有生成本地交付副本才算流程完成；未交付的合法前缀为 INCONCLUSIVE。

这是本例主动选定的保守策略：注释变化也要求重测，不代表所有项目都应采用这项策略。工具不判断测试是否覆盖完整需求，也不证明测试通过的程序没有其他错误。

## 实际执行什么

```text
python -X utf8 examples/agent_rule_quality/run_demo.py
```

命令使用当前 Python 解释器，离线运行且仅需标准库。请从仓库根目录执行，或使用脚本绝对路径。

程序从 [fixture](fixture/) 复制微型项目，在独立目录中改写返回值、运行一个固定的 unittest、读取差异、复制交付文件。故意违规的动作不会调用待测规则阻止自身，否则无法观察规则是否漏检。`test` 动作依据实际结果记录为 `test_pass` 或 `test_fail`，不从请求名称推断结果。

每步保留源文件、固定测试和摘要；测试步骤保留命令、退出码、实际执行数量、stdout/stderr。运行异常、零测试、跳过测试、超时或结果与退出码不符都属于 ERROR。Python 使用 `-B` 避免反复改写微型文件时复用字节码缓存。

动作由脚本安排，程序真实执行；这不是自主 LLM Agent 的能力评测。两套缺陷规则是故意注入的负对照，不是真实生产故障。

## 九个固定案例

| ID | 执行 | 预期 |
|---|---|---|
| normal | 修改 → 测试通过 → 交付 | PASS |
| read_after_test | 修改 → 测试通过 → 只读差异 → 交付 | PASS |
| fix_after_failure | 修改 → 失败 → 修正 → 测试通过 → 交付 | PASS |
| retest_after_edit | 测试通过 → 再修改 → 重测通过 → 交付 | PASS |
| untested_delivery | 修改 → 未测交付 | FAIL |
| failed_delivery | 测试失败 → 交付 | FAIL |
| stale_test | 测试通过 → 改成另一份正确代码 → 未重测交付 | FAIL |
| latest_failure | 曾通过 → 修改 → 最新测试失败 → 交付 | FAIL |
| unfinished | 修改 → 测试通过，未交付 | INCONCLUSIVE |

“另一份正确代码”是微型程序的人工设定，采集器在 `stale_test` 中并不偷偷重测；它只能如实记录为当前未测。

## 三套规则和预期诊断

三份模型的变量、初始状态、动作赋值、公共不变量与终止条件相同，仅交付守卫不同：

| 模型 | 交付条件 | 预期体检 |
|---|---|---|
| [reasonable](model_reasonable.json) | 当前验证状态为 passed | PASS，9/9 匹配 |
| [permissive](model_permissive.json) | 历史上曾通过 | FAIL，漏检 stale_test、latest_failure |
| [restrictive](model_restrictive.json) | 当前通过且上一动作为测试 | FAIL，误拦 read_after_test |

公共不变量只表达“当前 passed 必须有历史通过记录”，不把交付需求重新写进不变量，以免掩盖过宽守卫。文件摘要被采集器抽象为 `validation`，模型本身不分析文件或代码。

三套模型内部检查均 PASS；**这只说明声明模型满足自己的不变量，并没有验证这些规则忠实表达上述需求。** 独立案例提供了不同的判断依据，但案例标签也需要人工审阅。

终端输出应包含：

```text
reasonable: 模型 PASS / 体检 PASS / 误拦 0 / 漏检 0 / 符合预期
permissive: 模型 PASS / 体检 FAIL / 误拦 0 / 漏检 2 / 符合预期
restrictive: 模型 PASS / 体检 FAIL / 误拦 1 / 漏检 0 / 符合预期
演示成功：三套规则的差异符合预期。
```

## 输出与复用

默认在本目录 `reports/demo/run-<唯一编号>/` 保存：

- 独立标注快照 `cases.json`、实际轨迹案例集 `suite.json`、三份模型快照。
- 每个案例的工作目录、逐步文件快照、`trace.json`、`evidence.json`，以及发生交付时的 `delivery/`。
- 各模型的体检子目录，含输入快照、`report.json`、`report.md`。
- `demo_result.json`，记录本次各模型报告的相对路径与预期核对结果。

每次新建目录，不覆盖旧报告或修改示例原件。自定义根目录相对于当前工作目录：

```text
python -X utf8 examples/agent_rule_quality/run_demo.py --outdir "my reports"
```

演示返回 `0` 表示九个案例与三模型诊断符合预期；结果不符返回 `1`；运行或输入错误返回 `2`。这里返回 `0` 不表示两套缺陷规则通过体检。

针对单个模型重复体检时，把下面的占位符替换为终端打印的本次演示绝对路径：

```text
python -X utf8 scripts/check_rule_quality.py --model examples/agent_rule_quality/model_permissive.json --suite "<本次演示目录>/suite.json"
```

该命令应返回 `1`，并报告两个漏检。接入自己的模型与案例见[规则体检教程](../../references/rule-quality-quickstart.md)。
