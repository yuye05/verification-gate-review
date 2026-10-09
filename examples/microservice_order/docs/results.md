# 付款与发货流程的模型结果

需求 REQ-ORDER-001：发货状态必须满足已付款。

模型只有 paid、shipped 两个布尔变量，声明状态组合为 4 个。
从两个变量都为 false 的初始状态出发，正确模型应有 3 个可达状态：
未付款未发货、已付款未发货、已付款已发货。

这些计数是 expected_results.json 中人工可独立核算的预期值；实际运行结果
以 reports/pass/门禁报告_合成自检.json 的 model_check 段为准。

付款和发货在这里是原子转换，未建模网络、消息队列、重试、退款或服务代码。
负例故意删除 ship 的付款守卫，检查器应找到一步发货的反例，关联回 REQ-ORDER-001。

## 独立程序执行轨迹

本地 order_program.py 独立实现相同业务动作，不读取模型。normal 场景实际执行 pay → ship；
unpaid_shipping 场景使用故意遗漏付款检查的实现，从初始状态直接执行 ship。
两种轨迹都对照正确模型：前者模型/轨迹均 PASS，后者模型 PASS、轨迹 FAIL，定位第 1 步 ship。
缺陷记录的 after 为 paid=false、shipped=true，确实违反 REQ-ORDER-001。

报告分别生成到 reports/trace_pass/ 和 reports/trace_negative_control/。结果以本次运行命令、
退出码及报告的 model_check/trace_check 段为准，不将程序成功保存轨迹解释为检查通过。
轨迹只覆盖已采集的单实例顺序执行，不证明日志完整、源码所有行为或真实微服务系统正确。
