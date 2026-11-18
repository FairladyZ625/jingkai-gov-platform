const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');
const { tmpdir } = require('node:os');

const root = path.resolve(__dirname, '../..');
const data = path.join(root, 'prototype/v4/data');
const groups = ['gongwen', 'rules', 'minutes', 'enterprises'];
const read = file => JSON.parse(fs.readFileSync(path.join(root, file), 'utf8'));
const seeds = Object.fromEntries(groups.map(key => [key, read('data/seed/real/' + key + '.json')]));

test('逐条保留来源与日期，并按原始依据标注文种、效力和核实状态', () => {
  for (const key of groups) {
    const input = read('data/public/' + key + '.json').items;
    assert.equal(seeds[key].length, input.length);
    input.forEach((source, i) => {
      const row = seeds[key][i];
      assert.equal(row.source_url, source.source_url);
      assert.equal(row.fetched, source.crawled);
      assert.equal(row.verified, key === 'enterprises' && source.honor_verified);
      if (key === 'gongwen') {
        assert.ok(row.tags.includes(source.wenzhong));
        assert.equal(row.tags.includes('格式参考（非北京）'), source.region.startsWith('上海'));
      } else if (key === 'rules') {
        assert.equal(row.tags.includes('已失效'), source.status.startsWith('已失效'));
        assert.equal(row.status, source.status);
      } else if (key === 'minutes') {
        assert.ok(row.tags.includes('会议素材') && row.tags.includes('新闻通稿'));
      } else {
        assert.equal(row.name, source.name);
        assert.equal(row.tags.includes('未核实'), !source.honor_verified);
      }
    });
  }
});

test('已有知识库的页面也加载补充数据，保持企业台账独立并避免重复加载', () => {
  const window = { JK_REAL: {}, JK_REAL_KB: {}, JK_KB_EXAMPLES: [], JK_DATA: { enterprises: [] } };
  const writes = [];
  const document = { currentScript: { src: 'file:///prototype/v4/data/index.js' },
    readyState: 'loading', write: html => writes.push(html) };
  const run = name => vm.runInNewContext(fs.readFileSync(path.join(data, name), 'utf8'), { window, document });
  run('index.js');
  assert.deepEqual(writes, ['<script src="file:///prototype/v4/data/real-supplement.js"></script>']);
  run('real-supplement.js');
  assert.deepEqual(JSON.parse(JSON.stringify(window.JK_REAL_SUPPLEMENT)), seeds);
  run('index.js');
  assert.equal(writes.length, 1);
  assert.deepEqual(window.JK_DATA.enterprises, []);
  assert.deepEqual(window.JK_REAL_KB, {});
});

test('从公开快照重建的种子和离线脚本与提交内容逐字节一致', t => {
  const tmp = fs.mkdtempSync(path.join(tmpdir(), 'jk8-seed-'));
  t.after(() => fs.rmSync(tmp, { recursive: true, force: true }));
  for (const dir of ['scripts/data', 'prototype/v4/data', 'data/public']) {
    fs.mkdirSync(path.join(tmp, dir), { recursive: true });
  }
  const builder = 'scripts/data/build_real_supplement.py';
  fs.copyFileSync(path.join(root, builder), path.join(tmp, builder));
  for (const key of groups) {
    const file = 'data/public/' + key + '.json';
    fs.copyFileSync(path.join(root, file), path.join(tmp, file));
  }
  execFileSync('python3', [path.join(tmp, builder)]);
  for (const file of [...groups.map(key => 'data/seed/real/' + key + '.json'), 'prototype/v4/data/real-supplement.js']) {
    assert.ok(fs.readFileSync(path.join(tmp, file)).equals(fs.readFileSync(path.join(root, file))), file);
  }
});
