# 接入一个小型工作流

先按 [README](../README.md#快速开始)安装依赖。本文命令从仓库根目录执行，`python` 指同一个虚拟环境解释器。Windows 未激活环境时用 `.\.venv\Scripts\python.exe`，Linux/macOS 用 `.venv/bin/python`。

## 1. 定义状态与规则

用已有订单案例开始，而不是复制综合光学模板：

| 项目 | 示例含义 |
|---|---|
| 状态变量 | `paid`、`shipped`，都只有 `false` 和 `true` |
| 初始状态 | 未付款、未发货 |
| 动作 | `pay`、`ship`；每个动作含执行条件 `guard` 和状态赋值 `set` |
| 不变量 | 如果已发货，则必须已付款，关联需求 `REQ-ORDER-001` |
| 终止状态 | 已付款且已发货 |

在仓库内创建一个练习目录并复制[正确模型](../examples/microservice_order/order_model.json)：

```text
python -c "from pathlib import Path; import shutil; p=Path('examples/microservice_order/reports/my-workflow'); p.mkdir(parents=True); shutil.copyfile('examples/microservice_order/order_model.json', p/'order_model.json')"
```

如果目录已存在，此命令会停止，避免覆盖之前的练习；请使用新目录名并同步后续路径。
变量必须是有限域，动作守卫目前支持等值条件的合取，不支持任意 Python 表达式。

## 2. 从实际程序采集状态

先运行现有的独立程序，生成正常轨迹：

```text
python -X utf8 examples/microservice_order/order_program.py --scenario normal --out examples/microservice_order/reports/my-workflow/trace.json
```

接入自己的程序时，沿用以下采集方式。代码片段取自订单实现的核心过程，`order` 是实际业务对象，`actions` 是本次真正执行的动作：

```python
steps = []
for action in actions:
    before = order.state()
    getattr(order, action)()
    steps.append({"action": action, "before": before, "after": order.state()})
trace = {"steps": steps}
```

`state()` 必须返回新的状态快照，避免后续修改连带改变过去记录。用实际执行结果采集 `after`，不能根据模型推算它。
该格式记录已完成的原子动作；拒绝请求、动作中途异常、并发或多实例日志不能直接当作此格式输入。

生成的 JSON 有如下结构：

```json
{
  "steps": [
    {"action": "pay", "before": {"paid": false, "shipped": false}, "after": {"paid": true, "shipped": false}},
    {"action": "ship", "before": {"paid": true, "shipped": false}, "after": {"paid": true, "shipped": true}}
  ]
}
```

## 3. 配置并运行检查

在 `examples/microservice_order/reports/my-workflow/gate_config.json` 保存：

```json
{
  "model_check": {"model": "order_model.json", "max_states": 100},
  "trace_check": {"trace": "trace.json"},
  "output_dir": "reports"
}
```

这里的路径相对于配置文件目录。运行：

```text
python -X utf8 scripts/synthetic_check.py --config examples/microservice_order/reports/my-workflow/gate_config.json
```

预期模型 PASS、轨迹 PASS、退出码 `0`，报告位于练习目录的 `reports/门禁报告_合成自检.json`。
第二层可以独立运行；这份配置没有数字扫描，也没有替你完成人工交付审查。

## 4. 解读结果

| 结果 | 要检查什么 |
|---|---|
| 模型 PASS、轨迹 PASS | 声明模型和本次完整轨迹通过；仍需确认模型是否表达了真实需求 |
| 模型 PASS、轨迹 FAIL | 查看 `trace_check.reason/step/action` 和前后状态，核对程序及采集映射 |
| 模型 FAIL | 查看 `model_check.counterexample`；可能是规则本身允许坏状态 |
| INCONCLUSIVE | 状态搜索达到上限或轨迹尚未到终止状态，不能按通过处理 |
| 退出码 2 | 先解决输入/配置/文件错误，不使用旧报告作为本次结果 |

只有真实不变量违例才会附上模型声明的需求编号；普通字段错误、未知动作或守卫不匹配不一定有关联需求。

## 练习：修改模型守卫

此练习只修改副本，保留原模型和正常轨迹：

1. 将练习目录里的 `order_model.json` 另存为 `order_model_exercise.json`。
2. 找到 `ship` 动作，把 `guard` 从 `{"paid": true, "shipped": false}` 改成 `{"shipped": false}`，其余内容（特别是不变量）保持不变。
3. 新建同目录的 `gate_config_exercise.json`，内容如下。

```json
{
  "model_check": {"model": "order_model_exercise.json", "max_states": 100},
  "trace_check": {"trace": "trace.json"},
  "output_dir": "exercise-reports"
}
```

```text
python -X utf8 scripts/synthetic_check.py --config examples/microservice_order/reports/my-workflow/gate_config_exercise.json
```

预期**模型 FAIL、轨迹 PASS、总体 FAIL、退出码 1**。模型反例为初始状态直接 `ship`，关联 `REQ-ORDER-001`；正常轨迹仍合法，却不能抵消模型中的缺陷。
这与首页“正确模型遇到缺陷程序”的例子相反，有助于区分模型性质和一次程序执行。

## 值不值得接入

普通断言能在代码执行时检查局部条件；单元测试能覆盖指定输入；模型检查可以探索声明状态中的其他路径，轨迹检查可以独立核对记录是否符合规则。
如果只是两个简单条件，直接写断言可能足够；需要审查多步流程及可追溯反例时，再考虑建模和日志采集的成本。

日志遗漏、伪造、错误的状态映射或不完整的业务模型不会因为检查器 PASS 而消失。当前例子只支持单实例顺序流程，不是已部署微服务或通用 Agent 验证器。完整格式见[配置说明](configuration.md)。
