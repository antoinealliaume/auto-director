# -*- coding: utf-8 -*-
import os

import redis
from fastapi.responses import JSONResponse

REDIS_URL = os.environ.get('REDIS_URL', '')
LOGIN_LIMIT = max(5, min(30, int(os.environ.get('LOGIN_LIMIT', '10'))))
LOGIN_WINDOW = max(60, min(3600, int(os.environ.get('LOGIN_WINDOW_SECONDS', '600'))))


def _queue():
    return redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None


def attach(app):
    @app.middleware('http')
    async def security_middleware(request, call_next):
        path = request.url.path

        # Legacy bootstrap used to expose cloud database/queue connection strings.
        # It is intentionally disabled: local workers now use the HTTPS worker API.
        if path == '/api/worker/bootstrap':
            return JSONResponse(
                {'detail': 'Legacy worker bootstrap disabled. Use the HTTPS local-worker protocol.'},
                status_code=410,
                headers={'Cache-Control': 'no-store'},
            )

        q = None
        login_key = 'autodirector:security:login_failures'
        if path == '/api/login' and request.method == 'POST':
            try:
                q = _queue()
                if q and int(q.get(login_key) or 0) >= LOGIN_LIMIT:
                    return JSONResponse(
                        {'detail': 'Trop de tentatives. Réessaie dans quelques minutes.'},
                        status_code=429,
                        headers={'Retry-After': str(LOGIN_WINDOW), 'Cache-Control': 'no-store'},
                    )
            except Exception:
                q = None

        response = await call_next(request)

        if path == '/api/login' and request.method == 'POST' and q:
            try:
                if response.status_code == 401:
                    n = q.incr(login_key)
                    if n == 1:
                        q.expire(login_key, LOGIN_WINDOW)
                elif 200 <= response.status_code < 300:
                    q.delete(login_key)
            except Exception:
                pass

        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "media-src 'self' blob:; "
            "connect-src 'self' http://127.0.0.1:8765; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        if path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store, max-age=0'
        return response
