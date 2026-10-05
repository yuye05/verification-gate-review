# 设计说明与后续方向

## 三层门禁

数值一致性、算法/模型自检和人工对抗审查分别提供不同证据。
第二层新增可选有限模型检查，复用 JSON 配置和报告出口，没有引入外部求解器或新的交付阶段。

| 选择 | 原因 |
|---|---|
| 单一配置入口 | 适配不同项目，路径相对配置目录解析 |
| 检查按配置启用 | 数值还原与工作流安全性分别按实际需求执行 |
| 有限域和等值转换 | 语义可直接检查，不执行配置表达式或依赖 eval |
| BFS 和父节点路径 | 穷举可达状态，以最少动作数输出反例 |
| 上限返回 INCONCLUSIVE | 检查未完成时不冒充证明 |
| 保留人工复核层 | 复核数字语义、模型假设和答辩依据 |

## 可复现的订单案例

需求 `REQ-ORDER-001` 要求“发货必须已付款”。paid/shipped 两个布尔变量声明 4 个组合，正确模型可达状态为 3。
负对照删除付款守卫，预期找到“初始状态 → ship”的最短反例。
预期值可独立核算，实际结果由示例命令生成；仓库提交模型、配置和复核清单，不提交本机运行快照。

模型将付款和发货视为原子动作，不覆盖消息丢失、乱序、退款或实际服务代码。
模型性质、所测案例和实际实现正确性须分别表述。

## 验证方式

```bash
python -X utf8 evals/check_regressions.py
python -X utf8 scripts/check_consistency.py --config examples/microservice_order/gate_config.json
python -X utf8 scripts/synthetic_check.py --config examples/microservice_order/gate_config.json
# 负例预期退出码 1
python -X utf8 scripts/synthetic_check.py --config examples/microservice_order/gate_config_buggy.json
python -X utf8 scripts/synthetic_check.py --config references/gate_config.example.json --outdir ../evals/optical_smoke
```

当前回归入口覆盖 45 项，包括误差单位、数值解析、空检查、模型违例、死锁、循环和状态上限。
光学示例包含 9 个还原案例及 kurtosis 判据，所有结论以当次输出为准。

## 后续方向

| 方向 | 价值 | 前置条件 |
|---|---|---|
| 模型与执行轨迹一致性 | 将模型连接到程序行为 | 稳定的接口或日志轨迹格式 |
| 数值字段、单位和文档位置绑定 | 减少纯数值匹配误判 | 可维护的字段和单位定义 |
| 契约与变形测试 | 检查缺少独立真值的算法性质 | 有效的不变量或变形关系 |
| UML/OCL、Alloy/SMT 适配 | 扩展模型表达和验证规模 | 明确转换语义与依赖成本 |

这些方向尚未实现，不应作为现有能力宣传。优先从一个实际执行轨迹格式开始验证模型与实现的联系。

## 相关研究背景

模型、约束与工具结合可参考 [MSA-Lab 论文摘要](https://www.jos.org.cn/jos/article/abstract/6813)和
[UML 多视图模型一致性验证论文](https://doi.org/10.1109/APSEC66846.2025.00107)。
本工具提供独立的小型有限状态示例，不宣称复现这些研究或具备完整 UML/Alloy 工具链。
