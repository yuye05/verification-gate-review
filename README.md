# verification-gate-review

[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**检查小型工作流的有限状态模型与实际执行轨迹，定位违反规则的步骤。**

适合能描述业务状态、规则，并采集顺序执行记录的开发者。项目也保留数值一致性与算法自检能力，见[进阶使用](references/advanced-usage.md)。

A small Python tool for checking finite-state models and recorded sequential executions. The payment/shipping demo shows how a valid model can coexist with a buggy implementation. It checks declared models and observed traces, not arbitrary source code or all system behavior.

## 演示结果

规则很简单：**发货前必须已付款**。正确模型有 4 个状态组合，其中 3 个可达；两个独立程序分别执行正常流程和故意漏掉付款检查的流程。

| 程序执行 | 模型检查 | 轨迹检查 | 解释 |
|---|---|---|---|
| 付款 → 发货 | PASS | PASS | 本次记录符合规则并到达终止状态 |
| 未付款 → 直接发货 | PASS | FAIL | 模型没错，但程序第 1 步 `ship` 违反规则 |

以下摘自实际运行生成的缺陷报告，仅保留相关字段，省略本机路径、时间戳等元数据：

```json
{
  "verdict": "FAIL",
  "model_check": {"verdict": "PASS"},
  "trace_check": {
    "verdict": "FAIL",
    "reason": "guard_not_satisfied",
    "step": 1,
    "action": "ship",
    "before": {"paid": false, "shipped": false},
    "after": {"paid": false, "shipped": true},
    "requirement": "REQ-ORDER-001"
  }
}
```

## 快速开始

推荐使用 **64 位 Python 3.13**。依赖为 NumPy、SciPy；首次安装需要联网，安装完成后订单演示可离线运行。

### 获取源码

```text
git clone https://github.com/yuye05/verification-gate-review.git
cd verification-gate-review
```

没有 Git 时，在仓库页面选择 **Code → Download ZIP**，完整解压后进入包含 `requirements.txt` 的目录。不要直接在压缩包里运行，也不要仅下载一个脚本。

### Windows PowerShell

在源码目录运行，不需要激活虚拟环境或修改 PowerShell 执行策略：

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -X utf8 examples/microservice_order/run_demo.py
```

若 `python --version` 不是 3.13，可使用已安装的 `py -3.13` 创建环境。安装步骤报错时先停止，解决错误后再继续。

### Linux / macOS

下面是对应的操作方式。Ubuntu 已在 GitHub Actions 中通过依赖安装、回归检查与演示；以下虚拟环境安装步骤未在 Linux 实机逐条验证，macOS 尚未实测。

```bash
python3.13 --version
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -X utf8 examples/microservice_order/run_demo.py
```

后文的 `python` 均指这个虚拟环境的解释器；未激活时继续使用上面的完整路径。

### 查看结果

安装后每次只需一条命令：

```text
python -X utf8 examples/microservice_order/run_demo.py
```

输出应包含：

```text
normal: 模型 PASS / 轨迹 PASS / 符合预期
unpaid_shipping: 模型 PASS / 轨迹 FAIL / 符合预期
  原因: guard_not_satisfied；步骤: 1；动作: ship；需求: REQ-ORDER-001
演示成功：正常场景通过，缺陷场景被准确检出。
```

每次在 `examples/microservice_order/reports/demo/run-<唯一编号>/` 下保存模型副本、两份轨迹、配置及报告，终端会打印绝对路径。已有报告不会被覆盖；示例源文件不会被改写。

自定义输出根目录：

```text
python -X utf8 examples/microservice_order/run_demo.py --outdir "my reports"
```

演示入口的 `--outdir` 相对于**当前工作目录**；默认输出位于示例目录。可从任意目录用脚本绝对路径运行。底层检查脚本仍遵循原约定：配置内的路径和其 `--outdir` 相对于**配置文件目录**。

| 演示退出码 | 含义 |
|---|---|
| `0` | 两个场景都符合预期：正常通过、缺陷被准确检出 |
| `1` | 检查结果与演示预期不符 |
| `2` | 运行或输入错误，例如缺依赖、缺文件、报告损坏或输出不可写 |

**演示成功不代表缺陷程序通过，也不代表整套交付门禁通过。** 演示只运行模型与轨迹检查；底层检查器检测到缺陷时仍返回 `1`。演示入口会同时核对该退出码和本次报告，避免把崩溃当成成功检出。

### 安装与运行问题

| 问题 | 处理方式 |
|---|---|
| 缺少 NumPy/SciPy | 使用同一个 `.venv` 解释器执行 `-m pip install -r requirements.txt`；不要混用系统 pip |
| 下载失败或找不到匹配版本 | 确认是 64 位 Python 3.13，并检查网络、代理或包索引；保留完整错误，不关闭 TLS 校验 |
| 创建环境时报 `ensurepip`/权限错误 | 确认 Python 安装完整，项目目录和系统临时目录可写；受限执行环境可能需要在普通终端创建环境，不修改项目校验逻辑 |
| Linux 提示缺少 venv | 安装该系统发行版提供的 Python 3.13 venv 组件后重试 |
| 路径有中文或空格 | 给完整路径加引号；PowerShell 调用带引号的程序路径时在前面加 `&`；保留 `-X utf8` |
| 找不到报告 | 以本次终端打印的绝对路径为准；演示失败时不要拿以前的报告代替 |
| 报告是 FAIL/INCONCLUSIVE | 检查具体原因；缺陷演示的 FAIL 是预期结果，自己项目的 FAIL/INCONCLUSIVE 不能放行 |

## 接入自己的项目

从[最小接入教程](references/workflow-quickstart.md)开始：定义有限状态与规则 → 在实际动作前后记录状态 → 运行检查 → 阅读报告。

- [订单程序](examples/microservice_order/order_program.py)展示独立采集；不读取模型，也不从模型生成“实际状态”。
- [配置与轨迹格式](references/configuration.md)说明 JSON 字段及判定规则。
- [修改守卫的练习](references/workflow-quickstart.md#练习修改模型守卫)演示模型本身出错时的区别。

普通断言适合在代码中即时阻止错误，单元测试适合验证选定输入；本工具补充有限模型的状态搜索和记录后的轨迹核对。是否值得接入，取决于这些证据是否能抵消建模和采集成本。

## 其他能力与边界

[进阶使用](references/advanced-usage.md)保留数值一致性、通用算法/光学案例、三层门禁、手动运行各步骤及 Skill 用法。详细原理见[设计说明](references/design-notes.md)。

- 模型检查只穷尽声明的有限模型；达到状态上限返回 INCONCLUSIVE，不能当作证明完成。
- 轨迹检查只覆盖已记录的单实例顺序执行；不验证并发、分布式消息、活性或公平性。
- 日志完整性、状态映射、抽象假设仍需人工复核。SHA-256 标识输入，不证明日志来源真实。
- 数字扫描不理解语义或自动换算单位；合成测试不证明全部输入正确。
- `generic_check` 会执行本地 Python 模块，只使用来源可信、已经审查的代码。
- 工具不自动理解任意源码，不替代单元测试、代码审查或真实系统测试。

## 验证与开发

```text
python -X utf8 evals/check_regressions.py
python -X utf8 evals/check_demo.py
```

现有回归入口包含 86 项检查；另有 6 项演示端到端测试，覆盖正反例、重复运行、非仓库工作目录、中文/空格路径、异常与报告校验。两套测试均在独立临时目录运行。

本轮已在 Windows / Python 3.13.14 的独立虚拟环境安装并验证 NumPy 2.5.4、SciPy 1.18.1。依赖版本是本次实测记录，不是所有版本的兼容承诺。
2026-11-13，提交 `011a179` 的 [GitHub Actions 检查](https://github.com/yuye05/verification-gate-review/actions/runs/43448234837)在 Windows 和 Ubuntu 的 Python 3.13 环境中通过了依赖安装、核心回归、演示测试和实际演示。后续提交以最新 Actions 结果为准；macOS 尚未实测。

贡献方式见 [CONTRIBUTING.md](CONTRIBUTING.md)，变更见 [CHANGELOG.md](CHANGELOG.md)。反馈请提供运行命令、版本、预期与实际结果，并脱敏报告中的路径和业务数据。

## 许可证与作者

项目采用 [MIT License](LICENSE)。作者为 [Jimmy王（yuye05）](https://github.com/yuye05)，贡献与辅助工具使用记录见 [AUTHORSHIP.md](AUTHORSHIP.md)。
