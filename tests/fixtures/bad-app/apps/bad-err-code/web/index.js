export async function mount(el, ctx) {
  try {
    await ctx.api('/go');
  } catch (err) {
    if (err.code === 'typo_failed') ctx.toast(ctx.preview.errors.message(err), 'error');
  }
}
