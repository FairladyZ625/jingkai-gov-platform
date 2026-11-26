const test=require('node:test'), assert=require('node:assert/strict');
const {createContext,loadScript}=require('./mock.cjs');
test('离线Word是真实OOXML ZIP，保留中文及草稿标记',async()=>{
 const c=createContext({Blob,TextEncoder,Uint8Array,DataView});loadScript(c,'assets/word-export.js');
 const result=c.JKWord.export({title:'公开资料<&>',docNo:'演示〔2026〕1号',to:'各单位',paragraphs:['第一段\n第二行',''],sign:'工作组',date:'2026年11月26日'},{draft:true});
 assert.match(result.filename,/\.docx$/);assert.equal(result.blob.type,'application/vnd.openxmlformats-officedocument.wordprocessingml.document');
 const bytes=Buffer.from(await result.blob.arrayBuffer());assert.equal(bytes.readUInt32LE(0),0x04034b50);
 assert.ok(bytes.includes(Buffer.from('公开资料&lt;&amp;&gt;（草稿）')));assert.ok(bytes.includes(Buffer.from('<w:br/>')));
});
