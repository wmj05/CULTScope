"""TMDb API 客户端封装。

负责三件事：
1. 统一携带 Bearer Token 认证（Token 来自 .env，不写死在代码里）；
2. 对网络超时、HTTP 429 限流、5xx 服务端错误做自动重试；
3. 把错误转换成容易理解的 TmdbError。
"""

from __future__ import annotations

import time
from typing import Any

import requests


class TmdbError(Exception):
    """TMDb 请求失败。status_code 为 HTTP 状态码，网络异常时为 None。"""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class TmdbClient:
    """极简 TMDb 客户端，只封装本项目用到的搜索与详情接口。"""

    def __init__(
        self,
        bearer_token: str,
        base_url: str = "https://api.themoviedb.org/3",
        language: str = "zh-CN",
        timeout: int = 15,
        max_retries: int = 3,
        backoff: float = 1.5,
    ) -> None:
        if not bearer_token or not bearer_token.strip():
            raise TmdbError("未配置 TMDB_BEARER_TOKEN，请先在 backend/.env 中填写")

        self.base_url = base_url.rstrip("/")
        self.language = language
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.backoff = backoff

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {bearer_token.strip()}",
                "Accept": "application/json",
            }
        )

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """发起 GET 请求，失败时按次数退避重试。"""
        url = f"{self.base_url}{path}"
        query: dict[str, Any] = {"language": self.language}
        if params:
            query.update(params)

        last_error = "未知错误"

        for attempt in range(1, self.max_retries + 1):
            is_last_attempt = attempt == self.max_retries

            try:
                response = self.session.get(url, params=query, timeout=self.timeout)
            except requests.RequestException as exc:
                # 超时、连接失败、DNS 异常等都属于这一类
                last_error = f"网络异常（{exc.__class__.__name__}）"
                if is_last_attempt:
                    break
                wait = self.backoff * (2 ** (attempt - 1))
                print(f"  [重试 {attempt}/{self.max_retries}] {last_error}，{wait:.1f}s 后重试")
                time.sleep(wait)
                continue

            status = response.status_code

            if status == 200:
                try:
                    return response.json()
                except ValueError as exc:
                    raise TmdbError("TMDb 返回的内容不是合法 JSON") from exc

            if status == 401:
                raise TmdbError(
                    "TMDb 认证失败（HTTP 401）：Read Access Token 无效或已过期",
                    status_code=401,
                )

            if status == 404:
                raise TmdbError(f"TMDb 资源不存在（HTTP 404）：{path}", status_code=404)

            if status == 429 or 500 <= status < 600:
                last_error = f"TMDb 暂时不可用（HTTP {status}）"
                if is_last_attempt:
                    break

                if status == 429:
                    retry_after = response.headers.get("Retry-After", "")
                    wait = float(retry_after) if retry_after.isdigit() else self.backoff * 2
                else:
                    wait = self.backoff * (2 ** (attempt - 1))

                print(f"  [重试 {attempt}/{self.max_retries}] {last_error}，{wait:.1f}s 后重试")
                time.sleep(wait)
                continue

            # 其余 4xx（如 422 参数错误）重试没有意义，直接抛出
            raise TmdbError(
                f"TMDb 请求失败（HTTP {status}）：{response.text[:200]}",
                status_code=status,
            )

        raise TmdbError(f"{last_error}，已尝试 {self.max_retries} 次")

    def search_movie(self, query: str, year: int | None = None) -> list[dict[str, Any]]:
        """按片名搜索电影，可选按上映年份过滤。"""
        params: dict[str, Any] = {"query": query, "include_adult": "false"}
        if year:
            params["year"] = year
        data = self._get("/search/movie", params)
        return data.get("results", [])

    def movie_detail(self, movie_id: int) -> dict[str, Any]:
        """获取电影详情，并一次性附带关键词和演职员信息。"""
        return self._get(
            f"/movie/{movie_id}",
            {"append_to_response": "keywords,credits"},
        )
