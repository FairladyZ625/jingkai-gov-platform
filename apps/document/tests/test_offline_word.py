"""离线导出与 HTTP 导出一样交付可由 Word 库读取的 OOXML。"""
from io import BytesIO
from pathlib import Path
import subprocess

from docx import Document


def test_offline_word_roundtrip():
    root = Path(__file__).resolve().parents[3]
    script = """
const fs=require('node:fs'),vm=require('node:vm');
global.window=global;
vm.runInThisContext(fs.readFileSync('web/assets/word-export.js','utf8'));
(async()=>{const r=JKWord.export({title:'公开资料<&>',docNo:'演示〔2026〕1号',to:'各单位',paragraphs:['第一段\\n第二行',''],sign:'工作组',date:'2026年11月26日'},{draft:true});process.stdout.write(Buffer.from(await r.blob.arrayBuffer()));})();
"""
    result = subprocess.run(['node', '-e', script], cwd=root, capture_output=True, check=True)
    document = Document(BytesIO(result.stdout))
    assert document.paragraphs[0].text == '公开资料<&>（草稿）'
    assert '第一段\n第二行' in [p.text for p in document.paragraphs]
