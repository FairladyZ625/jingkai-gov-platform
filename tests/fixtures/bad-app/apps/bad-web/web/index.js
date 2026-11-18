// 反例：第三方包、越出 web/ 的相对路径、直接 fetch 平台接口。
import { h } from 'lodash';
import { helper } from '../../escape.js';

const records = fetch('/api/apps/other/records');
const version = fetch(`/api/v1/records`);

export async function mount(el) {
  el.append(h('p', {}, helper(records, version)));
}