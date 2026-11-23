// 构建可搬运的 file:// 验收包。只取 HEAD 的已审核运行资源，不递归打包工作区。
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {execFileSync: exec} = require('node:child_process');
const {createHash} = require('node:crypto');
const root = path.resolve(__dirname, '../..');
const git = (...args) => exec('git', args, {cwd: root, maxBuffer: 16 << 20});
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const sha = git('rev-parse', 'HEAD').toString().trim();
const output = path.resolve(process.argv[2] || '.');
const parent = fs.realpathSync(path.dirname(output));
if (parent === root || parent.startsWith(root + '/') || !/^t38-browser-[\w.-]+$/.test(path.basename(output))) {
  throw Error('请指定仓库外尚不存在的 t38-browser-* 目录');
}
const base = path.join(output, 'browser-fixture'), v4 = 'prototype/v4/';
const files = {}, runtime = new Set();
const write = (rel, bytes) => {
  fs.mkdirSync(path.dirname(path.join(base, rel)), {recursive: true});
  fs.writeFileSync(path.join(base, rel), bytes, {flag: 'wx'});
  files[rel] = {sha256: sha256(bytes)};
};
// 明确限定树中 blob 的模式和路径。不会跟随符号链接，也不读取未跟踪资料。
const entries = new Map(git('ls-tree', '-r', '-z', sha, '--', v4).toString().split('\0')
  .filter(Boolean).map(s => { const [meta, file] = s.split('\t'); return [file, meta.split(' ')]; }));
function blob(rel) {
  const p = v4 + rel, e = entries.get(p);
  if (!/^[\w./-]+$/.test(rel) || rel.split('/').some(s => !s || s.startsWith('.')) ||
      !e || !['100644','100755'].includes(e[0]) || e[1] !== 'blob') throw Error('不支持的运行资源：' + rel);
  return git('cat-file', 'blob', e[2]);
}
const entry = blob('index.html').toString();
const win = {};
const config = vm.createContext({window: win});
for (const f of ['config/app.config.js', 'config/apps.js']) vm.runInContext(blob(f).toString(), config);
if (win.JK_CONFIG.api.mode !== 'mock') throw Error('基线不是离线 mock 配置，请人工核查');
for (const m of entry.matchAll(/<(?:script src|link rel="stylesheet" href)="([^"]+)"/g)) {
  if (!m[1].includes("'")) runtime.add(m[1]);
}
for (const a of win.JK_APP_LIST.filter(a => a.enabled !== false)) {
  if (a.mock) runtime.add('mock/' + a.id + '.js');
  if (a.api) runtime.add('api/' + a.id + '.js');
  for (const f of [...a.css || [], ...a.files || []]) runtime.add('apps/' + a.id + '/' + f);
}
for (const f of ['real-supplement', 'real-policies', 'real-kb', 'kb-examples']) runtime.add('data/' + f + '.js');
for (const f of [...runtime].filter(f => f.endsWith('.css'))) {
  for (const [,url] of blob(f).toString().matchAll(/url\(["']?([^"')]+)["']?\)/g)) {
    if (!url.startsWith('data:')) runtime.add(path.posix.join(path.posix.dirname(f), url));
  }
}
fs.mkdirSync(output, {mode: 0o700}); // EEXIST 即停止；不覆盖旧证据。
for (const f of [...runtime].sort()) {
  const original = blob(f);
  // 清除包内公开样例口令的字面量（含重置回退），不接触外部账号配置。
  let result = original;
  if (f.endsWith('.js')) {
    let t = original.toString();
    for (const pass of new Set(win.JK_CONFIG.demoAccounts.map(a => a.password).filter(Boolean))) {
      for (const quote of ['"', "'"]) t = t.replaceAll(quote + pass + quote, quote + quote);
    }
    result = Buffer.from("if (!window.T38?.ready) throw Error('T38 隔离未建立');\n"+t);
  }
  write(v4 + f, result); files[v4 + f].sourceSha256 = sha256(original);
}
const start = entry.indexOf('<script src="config/app.config.js">'), end = entry.indexOf('</head>');
const hook = '<script src="mock/mock-api.js"></script>';
if (start < 0 || end <= start || !entry.slice(start,end).includes(hook) ||
    /<(script|link)\b/i.test(entry.slice(0,start)) || /<script\b/i.test(entry.slice(end))) throw Error('入口顺序变化，请复核隔离边界');
// 保留入口原有顶层 parser-blocking 脚本标签，不能将整个 head 置入一次
// document.write：那可能让依赖 DOMContentLoaded 的真实外壳错过启动事件。
const fragment = entry.slice(start,end).replace(/<script>([\s\S]*?)<\/script>/g,
  (_,src)=>'<script>if(window.T38?.ready){\n'+src+'\n}</script>')
  .replace(hook, '<script src="../../qa/seed.js"></script>\n' + hook)
  + '<script src="../../qa/probe.js"></script>';
const csp = "default-src 'none'; script-src file: 'unsafe-inline'; style-src file: 'unsafe-inline'; img-src file: data: blob:; font-src file: data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
const page = entry.slice(0,start).replace(/<title>/, '<title>【T38 隔离验收】')
  + '<meta http-equiv="Content-Security-Policy" content="' + csp + '"><meta name="referrer" content="no-referrer"><meta http-equiv="x-dns-prefetch-control" content="off">\n'
  + '<script src="../../qa/isolate.js"></script>\n' + fragment + entry.slice(end).replace('<div id="root"></div>',
    '<div id="root">T38 隔离启动中。若一直停在这里，请确认使用 file:// 打开完整解压包，勿降低浏览器安全设置。</div>');
write(v4 + 'index.html', page); files[v4 + 'index.html'].sourceSha256 = sha256(entry);
for (const name of ['isolate.js','seed.js','probe.js']) write('qa/' + name, fs.readFileSync(path.join(__dirname,name)));
for (const name of ['README.md','parking.txt','parking-original.txt']) write(name, fs.readFileSync(path.join(__dirname,name)));
write('MANIFEST.json', JSON.stringify({revision:sha, entry:v4+'index.html', files}, null, 2)+'\n');
// 外层归档和证据目录保持私有。包内均为可公开的文件，确保 box 由一个
// 用户解压、另一低权限浏览器用户读取时，不因构建机的 umask=077 而白屏。
for (const rel of Object.keys(files)) {
  const p=path.join(base,rel); fs.chmodSync(p,0o644);
  for (let dir=path.dirname(p);dir!==output;dir=path.dirname(dir)) fs.chmodSync(dir,0o755);
}
exec('tar', ['-czf', path.join(output,'browser-fixture.tar.gz'), '-C', output, 'browser-fixture'],
  {env:{...process.env,COPYFILE_DISABLE:'1'}});
console.log(JSON.stringify({revision:sha, output, runtimeFiles:runtime.size, archiveSha256:sha256(fs.readFileSync(path.join(output,'browser-fixture.tar.gz')))}));
