"""Private SearXNG discovery and bounded public-page reads, without model IO."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import socket
from datetime import UTC, datetime
from urllib.parse import unquote, urljoin, urlsplit

import dns.asyncresolver
import dns.exception
import dns.resolver
import httpcore
import httpx
from bs4 import BeautifulSoup

from core.config import get_settings
from infrastructure.llm.native_search import (
    WebResearchResult,
    WebSource,
    factual_result_allowed,
    validate_fact_question,
)

WEB_PROTOCOL = "searxng-v1"
MAX_BYTES = 2 * 1024 * 1024
MAX_TEXT = 12000
ENGINES = ("bing", "duckduckgo")


class WebReadError(ValueError):
    """Safe author-facing failure; remote bodies and secrets are never included."""


def search_snapshot() -> dict | None:
    endpoint = get_settings().web_search_url.rstrip("/")
    if not endpoint:
        return None
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise WebReadError("搜索服务地址配置无效")
    return {
        "protocol": WEB_PROTOCOL,
        "endpoint_hash": hashlib.sha256(endpoint.encode()).hexdigest(),
    }


def search_status() -> dict:
    try:
        configured = search_snapshot() is not None
    except ValueError:
        configured = False
    return {
        "available": configured,
        "backend": WEB_PROTOCOL,
        "reason": None if configured else "公开资料搜索尚未配置，请联系服务管理员。",
        "disclosure": "仅将通用事实问题发送至本站搜索服务及其上游搜索网站；"
        "读取公开网页，不发送作品原文。",
    }


def require_search_snapshot(snapshot: dict | None):
    if not snapshot or snapshot != search_snapshot():
        raise WebReadError("搜索服务配置已变化，请重新开启本次公开资料查证")


def search_snapshot_matches(snapshot: dict | None) -> bool:
    try:
        return bool(snapshot and snapshot == search_snapshot())
    except ValueError:
        return False


async def search_availability() -> dict:
    status = search_status()
    if not status["available"]:
        return status
    try:
        async with httpx.AsyncClient(
            timeout=2, trust_env=False, follow_redirects=False
        ) as client:
            response = await client.get(
                get_settings().web_search_url.rstrip("/") + "/healthz"
            )
            response.raise_for_status()
    except httpx.HTTPError:
        return {
            **status,
            "available": False,
            "reason": "搜索服务暂时无法连接，请稍后重试或联系管理员。",
        }
    return status


def public_url(value: str) -> str:
    try:
        url = httpx.URL(value)
        host = url.host.rstrip(".").lower()
        if (
            not value
            or len(value) > 2048
            or url.scheme not in {"http", "https"}
            or not host
            or "." not in host
            and ":" not in host
            or url.userinfo
            or url.port not in {None, 80, 443}
            or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa"))
        ):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError
        return str(url.copy_with(fragment=None))
    except (ValueError, httpx.InvalidURL) as error:
        raise WebReadError("该网页地址不在允许的公开读取范围内") from error


class PublicNetworkBackend(httpcore.AnyIOBackend):
    async def connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None
    ):
        # Connect to the inspected numeric address. TLS still uses the original
        # hostname in httpcore, so a second DNS lookup cannot rebind this socket.
        async with asyncio.timeout(timeout or 20):
            servers = get_settings().web_dns_servers
            if servers:
                resolver = dns.asyncresolver.Resolver(configure=False)
                resolver.nameservers = [
                    str(ipaddress.ip_address(value.strip()))
                    for value in servers.split(",")
                ]
                if any(
                    not ipaddress.ip_address(value).is_global
                    for value in resolver.nameservers
                ):
                    raise WebReadError("网页 DNS 必须使用公开地址")
                resolver.lifetime = 4

                async def resolve(kind):
                    try:
                        return [
                            record.address
                            for record in await resolver.resolve(host, kind)
                        ]
                    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
                        return []
                    except dns.exception.DNSException as error:
                        raise WebReadError("网页 DNS 解析未完成") from error

                results = await asyncio.gather(resolve("A"), resolve("AAAA"))
                ips = [ip for values in results for ip in values]
            else:
                addresses = await asyncio.get_running_loop().getaddrinfo(
                    host, port, type=socket.SOCK_STREAM
                )
                ips = list(dict.fromkeys(str(item[4][0]) for item in addresses))
            if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
                raise WebReadError("网页解析到了非公开地址，已停止读取")
            return await super().connect_tcp(
                ips[0],
                port,
                timeout=timeout,
                local_address=local_address,
                socket_options=socket_options,
            )


def material_allowed(text: str, title: str, url: str, protected_terms) -> bool:
    return factual_result_allowed(
        WebResearchResult(
            answer=text,
            sources=[WebSource(url=url, title=title)],
            source_coverage="cited",
        ),
        protected_terms=protected_terms,
    )


def plain_text(value: str) -> str:
    return BeautifulSoup(value, "html.parser").get_text(" ", strip=True)


async def search_public_fact(
    question, *, snapshot, before_request, protected_terms=(), private_texts=()
):
    require_search_snapshot(snapshot)
    try:
        question = validate_fact_question(
            question, protected_terms=protected_terms, private_texts=private_texts
        )
    except ValueError as error:
        raise WebReadError(str(error)) from error
    # Disable SearXNG bang/category overrides; the backend alone selects engines.
    if any(token.startswith(("!", ":", "!!")) for token in question.split()):
        raise WebReadError("请使用通用事实问题，不要指定搜索引擎指令")
    failures = []
    async with httpx.AsyncClient(
        timeout=20, trust_env=False, follow_redirects=False
    ) as client:
        for engine in ENGINES:
            require_search_snapshot(snapshot)
            await before_request()
            try:
                async with asyncio.timeout(20):
                    async with client.stream(
                        "POST",
                        get_settings().web_search_url.rstrip("/") + "/search",
                        data={
                            "q": question,
                            "format": "json",
                            "engines": engine,
                            "categories": "general",
                            "language": "auto",
                        },
                    ) as response:
                        response.raise_for_status()
                        body = bytearray()
                        async for part in response.aiter_bytes():
                            body.extend(part)
                            if len(body) > MAX_BYTES:
                                raise WebReadError("搜索结果超过读取上限")
                data = json.loads(body)
                if not isinstance(data, dict) or not isinstance(
                    data.get("results"), list
                ):
                    raise WebReadError("搜索服务未返回有效结果")
                if not data["results"] and data.get("unresponsive_engines"):
                    raise WebReadError("上游搜索未完成")
                hits, seen = [], set()
                for item in data["results"][:50]:
                    if not isinstance(item, dict):
                        continue
                    try:
                        url = public_url(str(item.get("url") or ""))
                    except WebReadError:
                        continue
                    title = plain_text(str(item.get("title") or ""))[:300]
                    snippet = plain_text(str(item.get("content") or ""))[:1500]
                    if url in seen or not material_allowed(
                        snippet, title, url, protected_terms
                    ):
                        continue
                    seen.add(url)
                    hits.append(
                        {
                            "url": url,
                            "title": title,
                            "snippet": snippet,
                            "engine": engine,
                            "coverage": "search_snippet",
                        }
                    )
                    if len(hits) == 5:
                        break
                return {
                    "hits": hits,
                    "omissions": failures,
                    "coverage": "仅搜索摘要，需读取网页后才能引用为查证依据",
                }
            except (httpx.HTTPError, TimeoutError, ValueError) as error:
                failures.append(
                    {
                        "engine": engine,
                        "reason": "搜索请求未完成",
                        "kind": type(error).__name__,
                    }
                )
    return {"hits": [], "omissions": failures, "coverage": "未取得搜索结果"}


async def read_public_page(url, *, before_request, protected_terms=()):
    url = public_url(url)
    if not material_allowed("", "", unquote(url), protected_terms):
        raise WebReadError("网页地址包含原作信息或越界内容")
    async with httpcore.AsyncConnectionPool(
        network_backend=PublicNetworkBackend(), retries=0
    ) as pool:
        for redirect in range(4):
            await before_request()
            try:
                async with asyncio.timeout(20):
                    async with pool.stream(
                        "GET",
                        url,
                        headers={
                            "Host": urlsplit(url).netloc,
                            "User-Agent": "NovelCraft-FactReader/1.0",
                            "Accept": "text/html,text/plain",
                            "Accept-Encoding": "identity",
                        },
                        extensions={
                            "timeout": {
                                key: 20 for key in ("connect", "read", "write", "pool")
                            }
                        },
                    ) as response:
                        headers = {key.lower(): value for key, value in response.headers}
                        if response.status in {301, 302, 303, 307, 308}:
                            if redirect == 3 or b"location" not in headers:
                                raise WebReadError("网页重定向次数过多或地址缺失")
                            url = public_url(
                                urljoin(url, headers[b"location"].decode("latin1"))
                            )
                            if not material_allowed(
                                "", "", unquote(url), protected_terms
                            ):
                                raise WebReadError("重定向地址包含原作信息或越界内容")
                            continue
                        if response.status != 200:
                            raise WebReadError("网页暂时不可读取")
                        mime = (
                            headers.get(b"content-type", b"")
                            .split(b";", 1)[0]
                            .strip()
                            .lower()
                        )
                        if (
                            mime not in {b"text/html", b"text/plain"}
                            or headers.get(b"content-encoding", b"identity")
                            != b"identity"
                        ):
                            raise WebReadError("仅支持未压缩的公开网页和纯文本")
                        body = bytearray()
                        async for part in response.aiter_stream():
                            body.extend(part)
                            if len(body) > MAX_BYTES:
                                raise WebReadError("网页超过读取上限")
                break
            except (
                httpcore.NetworkError,
                httpcore.TimeoutException,
                TimeoutError,
                OSError,
            ) as error:
                raise WebReadError("网页读取未完成，请使用其他来源") from error
    soup = BeautifulSoup(bytes(body), "html.parser")
    title = soup.title.get_text(" ", strip=True)[:300] if soup.title else "公开网页"
    for element in soup(
        ["script", "style", "nav", "footer", "header", "form", "noscript", "template"]
    ):
        element.decompose()
    root = soup.find("main") or soup.find("article") or soup
    text = root.get_text("\n", strip=True)
    if not text or not material_allowed(text, title, url, protected_terms):
        raise WebReadError("网页缺少正文或包含原作信息、越界指令，未采用")
    return {
        "url": url,
        "title": title,
        "text": text[:MAX_TEXT],
        "content_hash": hashlib.sha256(bytes(body)).hexdigest(),
        "text_hash": hashlib.sha256(text[:MAX_TEXT].encode()).hexdigest(),
        "retrieved_at": datetime.now(UTC).isoformat(),
        "excerpted": len(text) > MAX_TEXT,
        "coverage": "page_excerpt" if len(text) > MAX_TEXT else "page_text",
        "authority": "外部参考，不是作品正史或角色已知事实；引用仅限实际读取的正文。",
    }
