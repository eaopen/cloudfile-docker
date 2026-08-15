#!/usr/bin/env python3
"""图标视图 review 门禁（P2-02）。

评审清单「图标视图」的五条要求（拖拽框选 / Ctrl/Cmd 离散多选 / Shift 连续选择 /
全选当前页 / 多选后批量操作栏）全部是浏览器交互，没有 HTTP 可断言面。本矩阵因此
只有 0 条 api 用例，运行后把 5 条 ui 用例报告为 skipped，退出码 0 —— 它证明用例集
可装载、可计数，真正的验收留给未来的浏览器套件（见 docs/review-icon-cases.json）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_harness as H

REPO_NAME = 'review-icon'
CASE_FILE = os.path.join('docs', 'review-icon-cases.json')


def setup(ctx, admin_token):
    print('\n图标视图无 API 用例，跳过夹具准备。', flush=True)
    return {}


def build_executors(ctx, fix):
    return {}


if __name__ == '__main__':
    sys.exit(H.matrix_main(setup, build_executors, CASE_FILE))
