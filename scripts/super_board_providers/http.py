"""Bounded GET retries; writes are sent once and never followed across redirects."""
import json
import hashlib
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from .base import ProviderError


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTP:
    def __init__(self, base, token, timeout=15, attempts=3):
        self.base, self.token = base.rstrip('/'), token
        self.timeout, self.attempts = timeout, attempts
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, method, path, body=None, raw=False):
        if not path.startswith('/') or path.startswith('//') or '..' in path.split('/'):
            raise ProviderError('config', 'Invalid API path', 66)
        url = self.base + path
        headers = {'Accept': 'application/json', 'User-Agent': 'super-board-gitea'}
        if self.token:
            headers['Authorization'] = 'token ' + self.token
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        attempts = self.attempts if method == 'GET' else 1
        for attempt in range(attempts):
            retry_after = None
            try:
                with self.opener.open(urllib.request.Request(url, data=data, headers=headers, method=method),
                                      timeout=self.timeout) as response:
                    payload = response.read(16 * 1024 * 1024 + 1)
                    if len(payload) > 16 * 1024 * 1024:
                        raise ProviderError('invalid-response', 'API response exceeds safety limit')
                    if raw:
                        return payload.decode('utf-8'), dict(response.headers)
                    if not payload:
                        return None, dict(response.headers)
                    try:
                        return json.loads(payload), dict(response.headers)
                    except (ValueError, UnicodeError):
                        raise ProviderError('invalid-response', 'API did not return valid JSON')
            except urllib.error.HTTPError as error:
                status = error.code
                retry_after = error.headers.get('Retry-After')
                error.close()
                if method != 'GET' and status >= 500:
                    raise ProviderError('uncertain-write', 'Write outcome unknown; reconcile remote state before resuming')
                if status == 429 or status >= 500:
                    if attempt + 1 < attempts:
                        pass
                    else:
                        raise ProviderError('rate-limit' if status == 429 else 'unavailable',
                                            'API temporarily unavailable (HTTP %d)' % status)
                else:
                    kind = {401: 'auth', 403: 'forbidden', 404: 'missing', 409: 'conflict',
                            422: 'validation', 423: 'locked'}.get(status, 'http')
                    # Do not echo server bodies/URLs: proxies can reflect credentials.
                    raise ProviderError(kind, 'API request rejected (HTTP %d)' % status)
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError):
                if method != 'GET':
                    raise ProviderError('uncertain-write', 'Write outcome unknown; reconcile remote state before resuming')
                if attempt + 1 >= attempts:
                    raise ProviderError('unavailable', 'API connection failed or timed out')
            delay = min(4, 0.25 * 2 ** attempt + random.random() / 10)
            if retry_after and retry_after.isdigit():
                # Do not disregard a long Retry-After and immediately retry.
                if int(retry_after) > 5:
                    raise ProviderError('rate-limit', 'Server requested a longer pause; retry explicitly later')
                delay = max(delay, int(retry_after))
            time.sleep(delay)

    def pages(self, path, query=None):
        result, seen = [], set()
        query = dict(query or {})
        for page in range(1, 1001):
            params = dict(query, page=page, limit=100)
            data, headers = self.request('GET', path + '?' + urllib.parse.urlencode(params))
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ProviderError('invalid-response', 'Expected a paginated array of objects')
            if not data:
                return result
            signature = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
            if signature in seen:
                raise ProviderError('invalid-response', 'API pagination repeated a page')
            seen.add(signature)
            result.extend(data)
            if len(result) > 100000:
                raise ProviderError('invalid-response', 'API result exceeds record safety limit')
            # Continue to an empty page, even if the server caps limit below 100.
        raise ProviderError('invalid-response', 'API pagination exceeded safety limit')
