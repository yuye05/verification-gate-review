"""固定测试与结构化执行记录；采集器同时核对退出码和实际执行数量。"""

import json
import sys
import unittest

from subject import answer


class SubjectTests(unittest.TestCase):
    def test_answer(self):
        self.assertEqual(answer(), 2)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SubjectTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({"tests_run": result.testsRun, "failures": len(result.failures),
                      "errors": len(result.errors), "skipped": len(result.skipped)}))
    sys.exit(0 if result.wasSuccessful() else 1)
