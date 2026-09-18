import base64
from dataclasses import dataclass
import os
from pathlib import Path
import ssl
from urllib.parse import urlsplit, urlunsplit, urlencode


@dataclass
class Settings:
    database_url: str
    password: str
    session_secret: str
    api_key: str
    local: bool = False
    mode: str = "mock"
    model: str = ""
    model_key: str = ""
    model_base: str = "https://api.openai.com/v1"

    @classmethod
    def load(cls, env=None, ca_path=Path('/tmp/langgraph-ca.pem')):
        env = os.environ if env is None else env
        for key, size in [('APP_PASSWORD', 16), ('SESSION_SECRET', 32), ('APP_API_KEY', 32)]:
            if len(env.get(key, '')) < size:
                raise ValueError(f'{key} must be at least {size} characters')
        if len({env['APP_PASSWORD'], env['SESSION_SECRET'], env['APP_API_KEY']}) != 3:
            raise ValueError('Generate independent login, session and API secrets')
        local = env.get('LOCAL_DEVELOPMENT', '').lower() == 'true'
        uri = urlsplit(env.get('DATABASE_URL', ''))
        if uri.scheme not in ('postgres', 'postgresql') or not uri.hostname or not uri.port or not uri.username or not uri.password or uri.path in ('', '/'):
            raise ValueError('DATABASE_URL requires a PostgreSQL URI with credentials, host, port and database')
        if local:
            query = {'sslmode': 'disable'}
        else:
            try:
                pem = base64.b64decode(env.get('PG_CA_CERT_BASE64', ''), validate=True).decode('ascii')
                if not pem:
                    raise ValueError('Empty certificate')
                ssl.create_default_context(cadata=pem)
                ca_path.write_text(pem)
                ca_path.chmod(0o600)
            except (ValueError, UnicodeError, ssl.SSLError) as exc:
                raise ValueError('PG_CA_CERT_BASE64 must contain a valid base64 PEM CA') from exc
            query = {'sslmode': 'verify-full', 'sslrootcert': str(ca_path)}
        db = urlunsplit(('postgresql', uri.netloc, uri.path, urlencode(query), ''))
        mode = env.get('MODEL_MODE', 'mock')
        if mode not in ('mock', 'openai-compatible'):
            raise ValueError('MODEL_MODE must be mock or openai-compatible')
        model, key = env.get('MODEL_NAME', ''), env.get('MODEL_API_KEY', '')
        base = env.get('MODEL_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
        target = urlsplit(base)
        if mode != 'mock' and (not model or not key or target.scheme != 'https' or not target.hostname or target.username or target.query or target.fragment):
            raise ValueError('Real model mode requires MODEL_NAME, MODEL_API_KEY and an HTTPS MODEL_BASE_URL')
        return cls(db, env['APP_PASSWORD'], env['SESSION_SECRET'], env['APP_API_KEY'], local, mode, model, key, base)
