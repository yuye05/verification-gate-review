"""独立订单程序：采集实际状态变化，不读取验证模型。"""

import argparse
import json
from pathlib import Path


class Order:
    def __init__(self):
        self.paid = False
        self.shipped = False

    def state(self):
        return {"paid": self.paid, "shipped": self.shipped}

    def pay(self):
        if self.paid or self.shipped:
            raise ValueError("订单不能重复付款或在发货后付款")
        self.paid = True

    def ship(self):
        if not self.paid or self.shipped:
            raise ValueError("发货要求已付款且尚未发货")
        self.shipped = True


class BuggyOrder(Order):
    def ship(self):
        # 故意注入缺陷：漏掉付款检查，用于验证门禁能否发现实现违规。
        if self.shipped:
            raise ValueError("订单不能重复发货")
        self.shipped = True


def run_order(scenario):
    if scenario == "normal":
        order, actions = Order(), ("pay", "ship")
    elif scenario == "unpaid_shipping":
        order, actions = BuggyOrder(), ("ship",)
    else:
        raise ValueError(f"未知场景: {scenario}")
    steps = []
    for action in actions:
        before = order.state()
        getattr(order, action)()
        steps.append({"action": action, "before": before, "after": order.state()})
    return {"steps": steps}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成订单程序的实际执行轨迹")
    parser.add_argument("--scenario", choices=("normal", "unpaid_shipping"), required=True)
    parser.add_argument("--out", type=Path, required=True, help="输出 JSON 路径，相对于当前工作目录")
    args = parser.parse_args()
    trace = run_order(args.scenario)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已记录 {len(trace['steps'])} 个实际执行动作: {args.out.resolve()}")
