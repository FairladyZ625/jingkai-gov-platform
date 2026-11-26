/* 离线 DOCX：OOXML + ZIP store，无外部服务；HTTP 仍用服务端 Word 导出。 */
(function () {
  const utf8 = text => new TextEncoder().encode(text);
  const xml = text => String(text ?? '').replace(/[\x00-\x08\x0b\x0e-\x1f\x7f]/g,'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
  function crc32(bytes) { let crc = -1; for(const byte of bytes) { crc ^= byte; for(let i=0;i<8;i++) crc=(crc>>>1)^((crc&1)?0xedb88320:0); } return (crc^-1)>>>0; }
  function header(size, fields) { const out=new Uint8Array(size), view=new DataView(out.buffer); for(const [offset,value,bytes] of fields) bytes===2?view.setUint16(offset,value,true):view.setUint32(offset,value,true); return out; }
  function zip(files) {
    const local=[], central=[]; let offset=0, centralSize=0;
    for(const [filename,text] of Object.entries(files)) {
      const name=utf8(filename), data=utf8(text), crc=crc32(data);
      const h=header(30,[[0,0x04034b50,4],[4,20,2],[6,0x800,2],[14,crc,4],[18,data.length,4],[22,data.length,4],[26,name.length,2]]);
      local.push(h,name,data);
      const c=header(46,[[0,0x02014b50,4],[4,20,2],[6,20,2],[8,0x800,2],[16,crc,4],[20,data.length,4],[24,data.length,4],[28,name.length,2],[42,offset,4]]);
      central.push(c,name);centralSize+=46+name.length;offset+=30+name.length+data.length;
    }
    const n=Object.keys(files).length;
    return new Blob([...local,...central,header(22,[[0,0x06054b50,4],[8,n,2],[10,n,2],[12,centralSize,4],[16,offset,4]])],{type:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'});
  }
  function paragraph(text,align='left',title=false) {
    const parts=String(text??'').replace(/\r\n?/g,'\n').split(/(\n|\f)/).map(t=>t==='\n'?'<w:br/>':t==='\f'?'<w:br w:type="page"/>':`<w:t xml:space="preserve">${xml(t)}</w:t>`).join('');
    return `<w:p><w:pPr><w:jc w:val="${align}"/><w:spacing w:after="160" w:line="420"/></w:pPr><w:r><w:rPr><w:rFonts w:eastAsia="${title?'宋体':'仿宋'}"/><w:sz w:val="${title?44:32}"/>${title?'<w:b/>':''}</w:rPr>${parts}</w:r></w:p>`;
  }
  window.JKWord = {export(content,{draft=true}={}) {
    const title=String(content.title||'文稿').replace(/[\r\n\f]/g,' ')+(draft?'（草稿）':'');
    const body=[paragraph(title,'center',true),content.docNo&&paragraph(content.docNo,'center'),content.to&&paragraph(content.to),...(content.paragraphs||[]).map(p=>paragraph(p)),content.sign&&paragraph(content.sign,'right'),content.date&&paragraph(content.date,'right')].filter(Boolean).join('');
    const files={
      '[Content_Types].xml':'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
      '_rels/.rels':'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
      'word/document.xml':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>${body}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>`
    };
    return {filename:title.replace(/[\\/:*?"<>|\x00-\x1f\x7f]/g,'_')+'.docx',blob:zip(files)};
  }};
})();
