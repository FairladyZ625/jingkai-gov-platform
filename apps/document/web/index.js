// 公文协作脚手架入口：业务界面由后续 Issue 实现；此处满足 module 型挂载与界面规范门禁。
import { h, PageHeader, Card, EmptyState } from '/sdk/ui/index.js';

export async function mount(el) {
  el.replaceChildren(
    PageHeader({ title: "公文协作" }),
    Card({
      title: '脚手架',
      children: [
        EmptyState({
          title: '业务界面尚未接入',
          description: '后端健康检查已就绪；完整流程见关联业务 Issue。',
        }),
      ],
    }),
  );
}
