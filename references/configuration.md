# 配置与检查语义

`gate_config.json` 是配置入口。所有相对路径以配置文件所在目录为基准；CLI 的 `--outdir` 优先于 `output_dir`。
光学示例见 [gate_config.example.json](gate_config.example.json)，可运行模型示例见 [订单配置](../examples/microservice_order/gate_config.json)。

## 数值一致性

| 字段 | 含义 |
|---|---|
| `authoritative_json` | 权威 JSON 路径列表，递归展平 int/float 数值，排除 bool |
| `scan_dirs` | 待扫描目录，默认配置目录；目录不存在或无目标文件会报错 |
| `scan_globs` | 扩展名列表，默认 `.md/.txt/.json/.drawio`；不是文件名通配表达式 |
| `forbidden_numbers` | 旧数字列表，格式 `{"value": 数值, "label": "说明"}` |
| `forbidden_texts` | 废弃文本片段列表，按字符串命中 |
| `whitelist` | 孤儿检测可忽略的数字；不豁免旧口径检测 |
| `skip_dirs` | 按完整路径分段匹配的目录名，默认另排除 `.git/.claude/__pycache__` |
| `skip_files` | 按文件名精确匹配的排除项 |
| `core_docs` | 核心文档路径片段；核心数字须在至少一个匹配文档出现 |
| `core_key_fragments` | 权威 JSON key 路径中的核心片段；未配置时全部数值按核心处理 |
| `skip_key_fragments` | 不作为结果提取的 JSON key 路径片段 |
| `rel_tolerance` | 相对容差，默认 `0.002`；另加绝对容差 `0.002` |
| `output_dir` | 输出目录，默认配置文件目录 |

比较公式为 `abs(a-b) <= abs_tolerance + rel_tolerance * max(abs(a), abs(b))`。
旧数字使用更紧的相对/绝对容差 `0.0005`。权威来源、自定义配置文件、固定名称的门禁报告及工具脚本目录自动排除；重叠扫描目录会去重。

扫描支持带符号的数字、科学计数法和括号内结果，只过滤明确的 LaTeX `\tag{...}`。
孤儿候选沿用小数位数和数值域启发式，需要人工复核，不能作为通用语义一致性证明。

## 通用算法自检

```json
{
  "pass_threshold_pct": 0.5,
  "generic_check": {
    "module": "algorithm.py",
    "algo": "recover",
    "encoder": "arg_list",
    "error_fn": "rel",
    "cases": [{"truth": 100, "inputs": [100]}]
  }
}
```

该片段演示接口，`algorithm.py` 与 `recover` 需由使用者提供。`module` 是可信的本地 `.py` 路径，`algo` 必须是可调用函数，`cases` 不得为空。
真值字段默认为 `truth`，可通过 `truth_key` 指定。

| 编码方式 | 调用约定 |
|---|---|
| `arg_list`（默认） | list 展开为位置参数；其他输入作为单个参数 |
| `kw_args` | dict 展开为关键字参数 |
| `callback` | 先调用同模块的 `generator(truth, **inputs, **extra)`，再将返回的 list/dict 交给算法 |

callback 示例：

```json
{
  "generic_check": {
    "module": "algorithm.py",
    "algo": "recover",
    "encoder": "callback",
    "generator": "make_input",
    "cases": [{"truth": 7, "inputs": {"offset": 2}}]
  }
}
```

`rel` 与兼容名称 `rel_abs` 均返回 `100 * abs(estimate-truth) / abs(truth)`。
阈值优先使用段内的 `pass_threshold_pct`，否则继承全局值，默认 `0.5`。
`error_fn="abs"` 使用绝对误差，必须另配正有限数 `abs_tolerance`，单位与真值一致。

数组逐元素计算后取最大误差，要求形状一致。判定为严格小于阈值；零真值只有精确还原为零才通过相对误差检查。
空值、非有限结果、形状不符和算法异常不能通过。JSON 的 `error/error_unit/threshold` 表示实际度量，绝对误差不会伪装为百分比。

## 光学内置案例

| 段 | 作用与关键参数 |
|---|---|
| `order_alignment` | 整数级次谷还原，含 `n/band/d_range/jitter_cm1/d_true_list/ncos_theta_list` |
| `fft` | Airy 光谱 FFT 厚度还原，含 `n/band/d_range/r2/d_true_list/thetas_deg` |
| `kurtosis` | 纯正弦与强多光束判据，含 `n/band/r2/d_true/theta_deg/two_beam_max/strong_min` |

合成数据需遵循算法的输入约定。通过仅支持所选案例的结论，不能推广为全输入域证明。

## 有限状态模型检查

```json
{"model_check": {"model": "order_model.json", "max_states": 10000}}
```

模型 schema 见[正确订单模型](../examples/microservice_order/order_model.json)：

- `variables`：同类型布尔值、整数或字符串构成的非空有限域，不允许重复值。
- `initial`：全部变量的初始赋值，须在声明域内。
- `transitions`：唯一 `id`、可选等值 `guard` 和非空 `set`。守卫取逻辑与，赋值为原子转换；省略 guard 表示无条件启用。
- `invariants`：唯一 `id`、可选字符串 `requirement`、可选 `when`、非空 `assert`。含义为 `when → assert`；省略 when 表示始终要求 assert。
- `terminals`：允许结束的状态模式；其他无启用动作的可达状态判为死锁。

BFS 遍历可达状态，以父节点和动作回溯最短反例。穷尽后才可 PASS；违例为 FAIL；达到正整数 `max_states` 上限为 INCONCLUSIVE，第二层门禁退出 1。
报告保存状态/转换计数、需求编号、条件激活情况、不可达动作、检查完整性与模型哈希。

检查仅适用于声明的有限模型；未激活条件和不可达动作需要复核。工具不验证源码一致性、活性或公平性。

## 执行轨迹检查

```json
{
  "model_check": {"model": "order_model.json", "max_states": 100},
  "trace_check": {"trace": "reports/normal_trace.json"}
}
```

`trace_check` 是可选段；存在时必须且只能包含非空字符串 `trace`，不能以 `{}` 或 null 表示关闭。
须同时配置 `model_check.model`，轨迹和 BFS 使用同一模型。模型须声明非空 `terminals`。
路径相对于配置目录解析；未配置本段时，报告中的 `sections_checked.trace_check=false`、`summary.t_trace_ok=null`。

轨迹必须是仅含 `steps` 的 JSON 对象。`steps` 为非空列表，每项必须且只能包含以下三个字段：

```json
{
  "steps": [
    {
      "action": "pay",
      "before": {"paid": false, "shipped": false},
      "after": {"paid": true, "shipped": false}
    },
    {
      "action": "ship",
      "before": {"paid": true, "shipped": false},
      "after": {"paid": true, "shipped": true}
    }
  ]
}
```

`action` 为非空字符串，匹配模型转换的 `id`。before/after 必须完整赋值全部模型变量，不能包含额外变量；值须在有限域内且类型一致，布尔值不能用 0/1 替代。
第一版仅接受从模型初始状态开始的一条顺序、完整业务轨迹，记录已执行的动作；不解释拒绝请求、并发事件、时间戳或网络日志。

`scripts/trace_check.py` 的 `check_trace(model, trace)` 先校验整份轨迹格式，再依次检查初始状态、相邻记录连续性、实际状态不变量、动作声明、守卫和原子赋值。
赋值之外的变量必须保持原值。最后状态须匹配至少一个 terminal；合法前缀未终止返回 `INCONCLUSIVE`，原因 `trace_not_terminal`。

| 情况 | 结果 |
|---|---|
| 全部记录符合模型且到达终止状态 | 轨迹 PASS |
| 初始状态不符、记录不连续、未知动作、守卫不满足、状态不符或不变量违例 | 轨迹 FAIL |
| 格式合法且符合模型，但末尾未终止 | 轨迹 INCONCLUSIVE |
| 空轨迹、缺失/额外字段、变量或值/类型错误、缺少模型/终止定义、文件或 JSON 错误 | 配置/输入错误，退出码 2 |

轨迹报告位于原 `门禁报告_合成自检.json` 的 `trace_check` 段：

- `scope="observed_execution_trace"`，`total_steps/steps_checked` 记录动作总数和核对到的位置；`complete=true` 仅表示全部动作通过且到达声明终止状态。
- FAIL 给出从 1 开始的 `step`、`action`、`before/after`、`reason`、适用的 `expected_before/expected_guard/expected_after/expected_actions`，以及截至违规步骤的 `execution_prefix`。
- `invariant_violations` 只包含实际 before/after 状态确实违反的不变量，标记 `phase`、条件和断言。每项仅在模型有非空需求编号时附 `requirement`；顶层 `violated_invariant/requirement` 对应首个违例。单纯的动作/守卫/状态匹配失败不会凭空关联需求。
- `model_sha256/trace_sha256` 为本次读取文件的哈希。模型结果仍单独保存在 `model_check` 段。

轨迹 FAIL/INCONCLUSIVE 阻止第二层通过并返回 1。即使轨迹 PASS，模型 FAIL 或达到状态上限仍阻止总体通过。
报告中的执行前缀是本次运行证据，不是 BFS 搜索得到的最短模型反例。

示例程序不读取模型，独立采集实际状态；运行方式见 [README 演示](../README.md#演示模型正确程序仍可能出错)。
接入其他程序时需保证动作和变量映射一致，并人工复核采集完整性。连续性检查和输入哈希不能证明日志没有遗漏，也不能证明未观测的程序执行正确。

## 输出及迁移

- 一致性输出 Markdown；第二层输出 JSON，`sections_checked` 标明范围，未运行项的 summary 为 null。
- 退出码 0/1/2 表示脚本通过、检查失败或未完成、配置或输入错误。一致性 0 仍可能含复核项。
- 从旧版本迁移时，`rel` 已统一为百分数；`abs` 需改用 `abs_tolerance`；callback 须指定 generator。
- 旧口径 FAIL 现在返回非零退出码，自动化调用方应检查进程状态和本次报告。
- 新增 `trace_check`、`sections_checked.trace_check` 和 `summary.t_trace_ok`；旧配置无须修改，消费者应允许这些新增字段。输入错误不会生成成功报告，旧报告不能替代本次结果。
