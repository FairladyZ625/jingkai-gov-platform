#!/usr/bin/env bash
# 生成开发计划页数据（prototype/v4/plan-data.json / plan-data.js）
# 用法：scripts/gen-plan-data.sh [issues.json 路径]；需要 gh 已登录（公开仓库，只读）
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/gen_plan_data.py "$@"
