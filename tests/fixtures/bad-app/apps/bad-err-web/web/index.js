// 反例：把错误码拼进文案、直接展示 err.message。
import { ErrorState } from '/sdk/ui/index.js';

export async function mount(el, ctx) {
  try {
    await ctx.api('/x');
  } catch (err) {
    ctx.toast(`${err.message}（${err.code}）`, 'error');
    ctx.toast('失败：' + err.code, 'error');
    ctx.toast(err.message, 'error');
    el.append(ErrorState({ title: '读取失败', code: err.code }));
    // 注释里的 err.message 与 `${err.code}` 不算
  }
}
