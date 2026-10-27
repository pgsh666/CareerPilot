"""Explicit local QA server: real MySQL/auth/storage; deterministic model and ASR fixtures.

Not imported by app.main. It cannot make paid calls; the provider key is removed.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(BACKEND / '.deps'), str(BACKEND / 'tests')]

if __name__ == '__main__':
    if sys.argv[1:] != ['--offline-fixtures']:
        raise SystemExit('Use the explicit --offline-fixtures QA flag.')
    import uvicorn
    from sqlalchemy.engine import make_url
    from training_support import FakeGateway, FakeSpeech

    from app.config import Settings
    from app.main import create_app
    from app.speech_service import LocalSpeech

    source = Settings()
    url = make_url(source.database_url.get_secret_value())
    if source.environment != 'development' or url.host not in {'localhost', '127.0.0.1'} or url.database != 'careerpilot_app':
        raise SystemExit('QA requires the dedicated local development database.')
    settings = source.model_copy(update={'deepseek_api_key': None, 'cookie_name': 'careerpilot_qa_session',
                                         'allowed_origins': ['http://127.0.0.1:5175']})

    class BrowserSpeech(FakeSpeech):
        def tts(self, text):
            return LocalSpeech(settings).tts(text)

    fake = FakeGateway()
    app = create_app(settings, gateway_factory=lambda *_: fake, speech=BrowserSpeech())
    uvicorn.run(app, host='127.0.0.1', port=8001, proxy_headers=False)
