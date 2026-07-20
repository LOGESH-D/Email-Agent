"""
services/gmail/transport.py — Proxy-free requests transport for Google API client.

Replaces httplib2 with a requests.Session(trust_env=False) so that
pyngrok's HTTP_PROXY / HTTPS_PROXY env vars are completely ignored.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _purge_proxy_env() -> None:
    """Remove proxy env vars set by pyngrok."""
    for v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
              "ALL_PROXY", "all_proxy", "REQUESTS_CA_BUNDLE"):
        os.environ.pop(v, None)


def build_no_proxy_http(credentials):
    """Return an AuthorizedSession with trust_env=False."""
    _purge_proxy_env()
    from google.auth.transport.requests import AuthorizedSession  # type: ignore
    session = AuthorizedSession(credentials)
    session.trust_env = False
    session.proxies   = {"http": "", "https": ""}
    return session


class _RequestsHttpResponse:
    """Maps requests.Response to the minimal interface googleapiclient needs."""
    def __init__(self, response):
        self.status   = response.status_code
        self.reason   = response.reason
        self._headers = {k.lower(): v for k, v in response.headers.items()}

    def __getitem__(self, key):
        return self._headers.get(key.lower(), "")

    def get(self, key, default=None):
        return self._headers.get(key.lower(), default)

    def items(self):
        return self._headers.items()


class RequestsHttpTransport:
    """
    Drop-in replacement for httplib2.Http using a proxy-free requests.Session.
    Pass an instance as the `http` argument to googleapiclient.discovery.build().
    """
    connections = {}
    follow_redirects = True

    def __init__(self, authorized_session):
        self._session = authorized_session

    def request(self, uri, method="GET", body=None, headers=None, **_kwargs):
        _purge_proxy_env()
        resp = self._session.request(method=method, url=uri,
                                     data=body, headers=headers or {})
        return _RequestsHttpResponse(resp), resp.content
