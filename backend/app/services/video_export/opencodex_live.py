"""OpenCodex gpt-live literal reader, using Lingua's local WebRTC bridge."""
import asyncio
import json
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

from app.config import settings
from app.services.video_export.ffmpeg_runner import run_ffmpeg

VOICES = ('cove','juniper','maple','spruce','ember','vale','breeze','arbor','sol')
PROVIDER = 'opencodex_live'

def runtime_config():
    root=Path(settings.video_tts_live_lingua_dir or '')
    bridge=root/'resources/live-dub.cjs'
    playwright=root/'.preview-runtime/browser-check/node_modules/playwright-core'
    if not (playwright/'package.json').is_file():playwright=root/'node_modules/playwright-core'
    browser=Path(settings.video_tts_live_browser or '')
    node=shutil.which('node')
    try:
        url=urlsplit(settings.video_tts_live_base_url)
        valid=url.scheme in ('http','https') and url.hostname in ('127.0.0.1','localhost','::1') and not url.username and not url.password and not url.query and not url.fragment and url.path in ('','/')
        _=url.port
    except ValueError:valid=False
    if not valid:raise RuntimeError('OpenCodex Live chỉ nhận proxy loopback hợp lệ')
    if not node or not bridge.is_file() or not (playwright/'package.json').is_file() or not browser.is_file():
        raise RuntimeError('Thiếu runtime OpenCodex Live: cần Node, Lingua live-dub, Playwright và browser executable')
    return dict(node=node,bridgePath=str(bridge),playwrightPath=str(playwright),browserPath=str(browser),baseUrl=settings.video_tts_live_base_url)

def configured():
    try:runtime_config();return True
    except RuntimeError:return False

class OpenCodexLiveTTSEngine:
    name=PROVIDER
    def __init__(self,*,model='cove',timeout=None):
        if model not in VOICES:raise RuntimeError('Giọng OpenCodex Live không được hỗ trợ')
        self.model=model
        self.timeout=float(timeout or settings.video_tts_live_timeout_seconds)

    async def synthesize(self,*,text,out_path):
        if not text or not text.strip():return None
        if len(text)>2000:raise RuntimeError('Mỗi lượt gpt-live tối đa 2000 ký tự')
        runtime=runtime_config()
        output=Path(out_path);output.parent.mkdir(parents=True,exist_ok=True)
        raw=output.with_name(output.stem+'.live.part')
        helper=Path(__file__).with_name('live_reader.cjs')
        payload={**runtime,'text':text.strip(),'voice':self.model,'output':str(raw),'timeoutMs':int(self.timeout*1000)}
        process=await asyncio.create_subprocess_exec(runtime['node'],str(helper),stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
            **({'creationflags':0x08000000} if sys.platform=='win32' else {}))
        try:
            try:
                stdout,stderr=await asyncio.wait_for(process.communicate(json.dumps(payload,ensure_ascii=False).encode()),timeout=self.timeout+20)
            except BaseException:
                if process.returncode is None:process.kill();await process.wait()
                raise
            if process.returncode!=0:
                # Never include command lines, raw headers or proxy responses in public errors.
                detail=stderr.decode(errors='replace').strip()
                allowed=('gpt-live did not read the requested text verbatim','Live narration was silent','gpt-live narration timed out')
                raise RuntimeError(detail if detail in allowed else 'OpenCodex Live không hoàn tất lời đọc; kiểm tra proxy và kết nối')
            result=json.loads(stdout.decode())
            if not result.get('ok') or not raw.is_file() or raw.stat().st_size<44:raise RuntimeError('OpenCodex Live không trả audio hợp lệ')
            target=output.with_suffix('.wav') if output.suffix.lower() not in ('.wav','.mp3') else output
            if result.get('format')=='wav' and target.suffix.lower()=='.wav':raw.replace(target)
            else:
                await run_ffmpeg(['-i',str(raw),'-vn','-ar','24000','-ac','1','-y',str(target)],timeout=30)
            return target
        finally:raw.unlink(missing_ok=True)
