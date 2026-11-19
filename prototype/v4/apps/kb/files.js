/* 知识库 · 浏览器端文件读取（真实解析 txt / md / docx；pdf 尝试抽取文字，抽不出时标"模拟解析"）
 * 正式环境：文件原样上传，由后端 MinerU 解析（含扫描件 OCR、表格、页码）。 */
(function () {
  const EXT = (n) => (String(n).match(/\.([a-z0-9]+)$/i) || [, ''])[1].toLowerCase();
  async function inflateRaw(u8) { const ds = new DecompressionStream('deflate-raw'); const s = new Blob([u8]).stream().pipeThrough(ds); return new Uint8Array(await new Response(s).arrayBuffer()); }
  async function inflate(u8) { const ds = new DecompressionStream('deflate'); const s = new Blob([u8]).stream().pipeThrough(ds); return new Uint8Array(await new Response(s).arrayBuffer()); }
  function decodeText(buf) {
    const u8 = new Uint8Array(buf);
    try { return new TextDecoder('utf-8', { fatal: true }).decode(u8).replace(/^\uFEFF/, ''); } catch (e) { /* 不是 UTF-8，按 GBK（Windows 记事本常见） */ }
    try { return new TextDecoder('gbk').decode(u8); } catch (e) { return new TextDecoder().decode(u8); }
  }
  /* docx = zip：读中央目录 → 解压 word/document.xml → 取 <w:t> 段落 */
  async function docxText(buf) {
    const dv = new DataView(buf); const u8 = new Uint8Array(buf);
    let eocd = -1; for (let i = buf.byteLength - 22; i >= Math.max(0, buf.byteLength - 65557); i--) if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
    if (eocd < 0) throw new Error('不是有效的 docx');
    const n = dv.getUint16(eocd + 10, true); let p = dv.getUint32(eocd + 16, true);
    for (let k = 0; k < n; k++) {
      const method = dv.getUint16(p + 10, true), csize = dv.getUint32(p + 20, true), nl = dv.getUint16(p + 28, true), xl = dv.getUint16(p + 30, true), cl = dv.getUint16(p + 32, true), off = dv.getUint32(p + 42, true);
      const name = new TextDecoder().decode(u8.subarray(p + 46, p + 46 + nl));
      if (name === 'word/document.xml') {
        const lnl = dv.getUint16(off + 26, true), lxl = dv.getUint16(off + 28, true); const start = off + 30 + lnl + lxl;
        const data = u8.subarray(start, start + csize); const xml = new TextDecoder().decode(method === 8 ? await inflateRaw(data) : data);
        return xml.replace(/<w:tab\/>/g, '\t').replace(/<\/w:p>/g, '\n').replace(/<w:br[^>]*\/>/g, '\n').replace(/<[^>]+>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&apos;/g, "'");
      }
      p += 46 + nl + xl + cl;
    }
    throw new Error('docx 里没有正文');
  }
  /* pdf：解压 FlateDecode 流，取 Tj/TJ 里的文字。中文 PDF 多用 CID 字体，常常取不到——如实标"模拟解析" */
  async function pdfText(buf) {
    const s = new TextDecoder('latin1').decode(new Uint8Array(buf)); let out = '';
    const re = /stream\r?\n/g; let m; let count = 0;
    while ((m = re.exec(s)) && count < 200) { count++;
      const st = m.index + m[0].length; const en = s.indexOf('endstream', st); if (en < 0) break;
      const dict = s.slice(Math.max(0, m.index - 300), m.index); let body = new Uint8Array(buf, st, en - st);
      try { if (/FlateDecode/.test(dict)) body = await inflate(body); } catch (e) { continue; }
      const t = new TextDecoder('latin1').decode(body);
      (t.match(/\((?:\\.|[^\\)])*\)\s*Tj|\[(?:[^\]]*)\]\s*TJ/g) || []).forEach((x) => { (x.match(/\((?:\\.|[^\\)])*\)/g) || []).forEach((y) => { out += y.slice(1, -1).replace(/\\([nrt()\\])/g, (a, b) => ({ n: '\n', r: '', t: ' ' }[b] || b)); }); out += /T[jJ]\s*$/.test(x) ? ' ' : ''; });
      out += '\n';
    }
    const readable = (out.match(/[A-Za-z0-9\u4e00-\u9fff]/g) || []).length;
    return readable > 40 ? out : '';
  }
  async function read(file) {
    const name = file.name || '未命名'; const ext = EXT(name); const size = file.size || 0;
    const base = { name, ext, size, from: '上传' };
    try {
      if (['txt', 'md', 'markdown', 'csv', 'json', 'html', 'htm'].includes(ext)) { let text = decodeText(await file.arrayBuffer()); if (/htm/.test(ext)) text = text.replace(/<(script|style)[\s\S]*?<\/\1>/gi, '').replace(/<br\s*\/?>|<\/p>|<\/div>|<\/h\d>/gi, '\n').replace(/<[^>]+>/g, ''); return Object.assign(base, { text, parse: 'real' }); }
      if (ext === 'docx') return Object.assign(base, { text: await docxText(await file.arrayBuffer()), parse: 'real' });
      if (ext === 'pdf') { const t = await pdfText(await file.arrayBuffer()); if (t) return Object.assign(base, { text: t, parse: 'real' }); return Object.assign(base, { parse: 'simulated', text: simulated(name) }); }
      if (['doc', 'wps', 'ofd'].includes(ext)) return Object.assign(base, { parse: 'simulated', text: simulated(name) });
      if (['mp3', 'm4a', 'wav', 'amr'].includes(ext)) return Object.assign(base, { error: '这是录音文件，请交给“会议记录”转写后再入库' });
      if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext)) return Object.assign(base, { error: '图片需要 OCR，原型暂不支持；正式版由后端识别文字' });
      return Object.assign(base, { error: '暂不支持 .' + ext + ' 格式' });
    } catch (e) { return Object.assign(base, { error: '读取失败：' + (e.message || e) }); }
  }
  function simulated(name) {
    const t = name.replace(/\.[a-z0-9]+$/i, '');
    return `${t}\n【模拟解析】原型在浏览器里读不出这个文件的正文（扫描件或 ${EXT(name).toUpperCase()} 格式）。正式版由后端 MinerU 解析全文、表格和页码，入库后即可检索。`;
  }
  /* 从对话框传来的 file（{name, ext, text, sample}）直接用其 text */
  function fromChat(f) { const ext = f.ext || EXT(f.name); if (f.text) return { name: f.name, ext, size: Number.isInteger(f.size) && f.size >= 0 ? f.size : f.text.length * 2, text: f.text, parse: f.sample ? 'sample' : 'real', from: '对话' }; return { name: f.name, ext, from: '对话', parse: 'simulated', text: simulated(f.name) }; }
  window.JKKBFiles = { read, fromChat, ext: EXT };
})();
