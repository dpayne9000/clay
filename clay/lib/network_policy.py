"""Shared outbound URL validation for workflow-controlled network requests."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import requests


MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
TIMEOUT_SECONDS = 15


class NetworkPolicyError(ValueError):
    pass


def _validated_addresses(url: str, *, allow_loopback_http: bool = False):
    parts = urlsplit(str(url or '').strip())
    if parts.username is not None or parts.password is not None:
        raise NetworkPolicyError('URL credentials are not allowed')
    if parts.scheme not in {'http', 'https'} or not parts.hostname:
        raise NetworkPolicyError('URL must contain an HTTP(S) host')
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise NetworkPolicyError(f'host could not be resolved: {exc}') from exc
    addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
    if not addresses:
        raise NetworkPolicyError('host resolved to no addresses')
    loopback = all(address.is_loopback for address in addresses)
    if parts.scheme != 'https' and not (allow_loopback_http and loopback):
        raise NetworkPolicyError('HTTPS is required except for explicit loopback development')
    refused = [str(address) for address in addresses if not address.is_global]
    if refused and not (allow_loopback_http and loopback):
        raise NetworkPolicyError(
            f'host resolves to non-public address(es): {", ".join(sorted(refused))}')
    return str(url), frozenset(addresses)


def validate_url(url: str, *, allow_loopback_http: bool = False) -> str:
    return _validated_addresses(
        url, allow_loopback_http=allow_loopback_http)[0]


def redirect_url(current: str, location: str) -> str:
    if not location:
        raise NetworkPolicyError('redirect response has no Location header')
    return urljoin(current, location)


def _connected_address(response) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Return the actual TCP peer used by requests/urllib3 or fail closed."""
    candidates = (
        getattr(getattr(response.raw, "_connection", None), "sock", None),
        getattr(getattr(getattr(getattr(response.raw, "_fp", None), "fp", None),
                        "raw", None), "_sock", None),
    )
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            return ipaddress.ip_address(candidate.getpeername()[0])
        except (AttributeError, OSError, TypeError, ValueError):
            continue
    response.close()
    raise NetworkPolicyError("could not verify the connected server address")


@dataclass(frozen=True)
class NetworkResponse:
    status_code: int
    headers: dict
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self):
        return requests.models.complexjson.loads(self.text)


def request(method: str, url: str, *, params=None, headers=None, json=None,
            allow_loopback_http: bool = False,
            timeout: int = TIMEOUT_SECONDS,
            max_bytes: int = MAX_RESPONSE_BYTES) -> NetworkResponse:
    """Request one URL while pinning policy to the peer actually connected.

    DNS is resolved before each hop.  The response is accepted only if the
    socket peer is one of those exact addresses, closing the gap where the HTTP
    client resolves a different, private address after policy validation.
    """
    session = requests.Session()
    session.trust_env = False
    current = str(url)
    current_method = method.upper()
    current_json = json
    try:
        for hop in range(MAX_REDIRECTS + 1):
            current, allowed = _validated_addresses(
                current, allow_loopback_http=allow_loopback_http)
            response = session.request(
                current_method, current,
                params=params if hop == 0 else None,
                headers=headers, json=current_json,
                timeout=timeout, allow_redirects=False, stream=True)
            peer = _connected_address(response)
            if peer not in allowed:
                response.close()
                raise NetworkPolicyError(
                    f"connected address {peer} was not the validated DNS answer")
            if response.status_code not in {301, 302, 303, 307, 308}:
                body = response.raw.read(max_bytes + 1, decode_content=True)
                response.close()
                if len(body) > max_bytes:
                    raise NetworkPolicyError(
                        f"response exceeds {max_bytes} byte limit")
                return NetworkResponse(
                    response.status_code, dict(response.headers), body)
            location = response.headers.get("Location", "")
            response.close()
            current = redirect_url(current, location)
            if response.status_code == 303 or (
                    response.status_code in {301, 302} and current_method == "POST"):
                current_method = "GET"
                current_json = None
        raise NetworkPolicyError("too many redirects")
    finally:
        session.close()
