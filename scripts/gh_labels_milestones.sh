#!/usr/bin/env bash
# Ben 授权后手动运行；已有条目保留原设置。
set -euo pipefail
repo=FairladyZ625/jingkai-gov-platform
# --dry-run：只读取现有条目并打印将要创建的 label 与 milestone，不调用写接口
dry_run=0
[[ "${1:-}" == "--dry-run" ]] && dry_run=1
existing_labels=$(gh api --paginate "repos/$repo/labels?per_page=100" --jq '.[].name')
label() {
  if ! grep -Fxq -- "$1" <<< "$existing_labels"; then
    if (( dry_run )); then echo "将创建 label: $1"; else gh label create "$1" --color "$2" --repo "$repo"; fi
  fi
}
for area in ai apps computer data deploy document enterprise kb meeting platform policy qa repo skills web; do
  label "area:$area" 1d76db
done
label priority:P0 b60205
label priority:P1 d93f0b
label priority:P2 fbca04
for kind in adapt direct none reference; do label "reuse:$kind" 0e8a16; done
for kind in bug chore feat test; do label "type:$kind" 5319e7; done

existing_milestones=$(gh api --paginate "repos/$repo/milestones?state=all&per_page=100" --jq '.[].title')
for title in 'M0 仓库与原型就位' 'M1 平台底座（卫华 core 落地）' 'M2 对话与知识库' 'M3 四个业务应用' 'M4 技能·电脑操作·联调演示'; do
  if ! grep -Fxq -- "$title" <<< "$existing_milestones"; then
    if (( dry_run )); then echo "将创建 milestone: $title"; else gh api --method POST "repos/$repo/milestones" -f title="$title" --silent; fi
  fi
done
