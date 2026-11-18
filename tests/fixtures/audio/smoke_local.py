"""使用已启动的内网服务做真实转写验收，CI 不运行本脚本。"""

import argparse
import asyncio
import json
from dataclasses import replace
from pathlib import Path

from jkq.transcribe import DEFAULT_HOTWORDS, transcriber_from_environment


def hotword_hits(sentences):
    text = ''.join(sentence['text'] for sentence in sentences)
    return [word for word in DEFAULT_HOTWORDS if word in text]


async def check(compare_no_hotwords):
    adapter = transcriber_from_environment()
    if adapter.source != 'local':
        raise SystemExit('请配置真实内网转写服务再运行验收。')
    audio = Path(__file__).with_name('demo-meeting.webm').read_bytes()
    result = await adapter.transcribe(audio)
    sentences = result['sentences']
    duration = result['durationMs']
    speakers = sorted({sentence['speaker'] for sentence in sentences})
    hits = hotword_hits(sentences)
    print(json.dumps({
        'source': result['source'], 'durationMs': duration, 'sentenceCount': len(sentences),
        'speakers': speakers, 'hotwords': hits,
    }, ensure_ascii=False), flush=True)
    assert not result['mock'] and 180000 <= duration <= 300000
    assert len(speakers) >= 2
    assert all(s['speaker'] and 0 <= s['startMs'] < s['endMs'] <= duration for s in sentences)
    assert [s['startMs'] for s in sentences] == sorted(s['startMs'] for s in sentences)
    assert set(hits) == set(DEFAULT_HOTWORDS)
    if compare_no_hotwords:
        baseline = await replace(adapter, hotwords=()).transcribe(audio)
        print(json.dumps({'hotwordsWithoutHints': hotword_hits(baseline['sentences'])}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compare-no-hotwords', action='store_true', help='同一录音额外执行一次空词表转写')
    asyncio.run(check(parser.parse_args().compare_no_hotwords))
