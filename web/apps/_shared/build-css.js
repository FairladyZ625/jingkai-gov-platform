// 把通用框架模板按应用前缀生成到各 app.css 的开头（保留各自的专属样式）
const fs = require('fs'), path = require('path');
const tpl = fs.readFileSync(path.join(__dirname, 'frame.css.tpl'), 'utf8');
const MARK = '/* ==== 以下为本应用专属样式 ==== */';
for (const id of ['policy', 'enterprise', 'meeting', 'document']) {
  const f = path.join(__dirname, '..', id, 'app.css');
  let own = fs.existsSync(f) ? fs.readFileSync(f, 'utf8') : '';
  own = own.includes(MARK) ? own.slice(own.indexOf(MARK)) : MARK + '\n' + own;
  fs.mkdirSync(path.dirname(f), { recursive: true });
  fs.writeFileSync(f, tpl.replace(/\.APP/g, '.app-' + id) + '\n' + own);
}
console.log('ok');
