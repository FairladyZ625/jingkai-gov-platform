// 反例：把校验问题的原始码直接渲染成徽标。
import { badge } from '/sdk/haiknow.js';

export function issueList(issues) {
  return issues.map((issue) => badge(issue.code, 'bad'));
}