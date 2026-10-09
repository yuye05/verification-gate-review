# 设计说明与后续方向

## 三层门禁

数值一致性、算法/模型自检和人工对抗审查分别提供不同证据。
第二层支持可选有限模型及执行轨迹检查，复用 JSON 配置和报告出口，没有引入外部求解器或新的交付阶段。

| 选择 | 原因 |
|---|---|
| 单一配置入口 | 适配不同项目，路径相对配置目录解析 |
| 检查按配置启用 | 数值还原与工作流安全性分别按实际需求执行 |
| 有限域和等值转换 | 语义可直接检查，不执行配置表达式或依赖 eval |
| BFS 和父节点路径 | 穷举可达状态，以最少动作数输出反例 |
| 上限返回 INCONCLUSIVE | 检查未完成时不冒充证明 |
| 共享模型校验与条件匹配 | BFS 与轨迹核对遵循同一有限域和转换语义 |
| 独立程序采集前后状态 | 将声明模型与一次实际执行连接起来 |
| 轨迹要求声明终止状态 | 合法但未完成的业务前缀不误报通过 |
| 保留人工复核层 | 复核数字语义、模型假设和答辩依据 |

## 可复现的订单案例

需求 `REQ-ORDER-001` 要求“发货必须已付款”。paid/shipped 两个布尔变量声明 4 个组合，正确模型可达状态为 3。
负对照删除付款守卫，预期找到“初始状态 → ship”的最短反例。
预期值可独立核算，实际结果由示例命令生成；仓库提交模型、配置和复核清单，不提交本机运行快照。

模型将付款和发货视为原子动作，不覆盖消息丢失、乱序、退款或实际服务代码。
模型性质、所测案例和实际实现正确性须分别表述。

## 模型与实际执行的联系

`order_program.py` 独立实现 Order 的付款、发货及故意漏掉付款检查的 BuggyOrder，不读取模型或根据模型生成状态。
每次实际执行前后采集全部可见业务状态。正常程序执行 pay → ship；缺陷程序在初始状态直接执行 ship。
两份运行轨迹都对照同一个正确模型：正常轨迹应 PASS，缺陷轨迹应 FAIL，而模型本身仍 PASS。

检查器先验证整份记录格式，再检查每步的初始/连续状态、动作、守卫、赋值及不变量。
未知动作和状态偏离不会跳过；域外值、布尔/整数混用或不完整记录属于输入错误。
报告关联实际不变量违例的需求编号，给出首次违规步骤及本次执行前缀；该前缀没有“全局最短”的含义。

第一版只支持单实例顺序业务流程。最终匹配 terminal 表示所记录轨迹按约定完成，不能证明日志完整或所有程序行为正确。
人工审查仍需核对动作/状态映射、记录采集、抽象假设和未覆盖行为。哈希仅标识输入，不认证来源。

## 验证方式

```bash
python -X utf8 evals/check_regressions.py
python -X utf8 scripts/check_consistency.py --config examples/microservice_order/gate_config.json
python -X utf8 scripts/synthetic_check.py --config examples/microservice_order/gate_config.json
# 负例预期退出码 1
python -X utf8 scripts/synthetic_check.py --config examples/microservice_order/gate_config_buggy.json
python -X utf8 examples/microservice_order/order_program.py --scenario normal --out examples/microservice_order/reports/normal_trace.json
python -X utf8 scripts/synthetic_check.py --config examples/microservice_order/gate_config_trace.json
python -X utf8 examples/microservice_order/order_program.py --scenario unpaid_shipping --out examples/microservice_order/reports/unpaid_shipping_trace.json
# 模型 PASS、轨迹 FAIL，预期退出码 1
python -X utf8 scripts/synthetic_check.py --config examples/microservice_order/gate_config_trace_buggy.json
python -X utf8 scripts/synthetic_check.py --config references/gate_config.example.json --outdir ../evals/optical_smoke
```

回归入口包含 86 项：保留原有 45 项，新增 41 项覆盖真实程序轨迹、守卫/赋值偏离、连续性、需求关联、输入错误、未终止及独立模型/轨迹判定。
光学示例包含 9 个还原案例及 kurtosis 判据，所有结论以当次输出为准。

## 后续方向

| 方向 | 价值 | 前置条件 |
|---|---|---|
| 多实例与真实服务轨迹接入 | 将现有单实例轨迹检查扩到系统行为 | 稳定的采集、实例关联和抽象映射 |
| 数值字段、单位和文档位置绑定 | 减少纯数值匹配误判 | 可维护的字段和单位定义 |
| 契约与变形测试 | 检查缺少独立真值的算法性质 | 有效的不变量或变形关系 |
| UML/OCL、Alloy/SMT 适配 | 扩展模型表达和验证规模 | 明确转换语义与依赖成本 |

这些方向尚未实现，不应作为现有能力宣传。已有本地顺序轨迹接口，后续须先验证采集与模型映射，再考虑分布式事件和更强的模型表达。

## 相关研究背景

模型、约束与工具结合可参考 [MSA-Lab 论文摘要](https://www.jos.org.cn/jos/article/abstract/6813)和
[UML 多视图模型一致性验证论文](https://doi.org/10.1109/APSEC66846.2025.00107)。
本工具提供独立的小型有限状态示例，不宣称复现这些研究或具备完整 UML/Alloy 工具链。
