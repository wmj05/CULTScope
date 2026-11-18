"""阶段 3.5.2B：IMDb 官方数据集安全下载器。

下载（默认输出到 `backend/data/raw/imdb/`，该目录已被 .gitignore 忽略）：
    https://datasets.imdbws.com/title.basics.tsv.gz
    https://datasets.imdbws.com/title.ratings.tsv.gz

用法（在仓库根目录）：
    python backend/scripts/download_imdb.py --help
    python backend/scripts/download_imdb.py --dataset basics --dry-run
    python backend/scripts/download_imdb.py --dataset all

行为约定：
    * 不指定 --dataset 时不开始下载，只打印帮助。
    * 采用流式写入 `.part` 临时文件，成功后用 os.replace 原子替换正式文件；
      失败时删除临时文件，已存在的正式文件保持不变。
    * 下载完成后本地校验：Content-Length、回读 SHA-256 一致性、gzip 可完整
      解压（含 CRC 与结束标记）。这些只证明本地文件完整可读，**不代表**
      与 IMDb 官方校验值一致；IMDb 未提供可信官方 SHA-256，脚本不编造。
    * 本地文件系统错误（建目录、建临时文件、写入、flush、fsync、磁盘空间
      查询）统一转换为 DownloadError，并尽力清理本次创建的临时文件。
    * 仅对网络类错误做有限次重试与指数退避。
    * 下载前检查剩余磁盘空间；响应头提供 Content-Length 时再检查一次。
    * 未实现断点续传：IMDb 文件为周期性全量替换，直接追加旧数据无法验证
      文件身份，因此每次完整下载，避免 Range 不匹配造成数据损坏。
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import http.client
import os
import shutil
import socket
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = BACKEND_DIR / "data" / "raw" / "imdb"

CHUNK_SIZE = 1024 * 1024
DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 2.0
MAX_BACKOFF = 30.0
DEFAULT_MIN_FREE_GB = 1.0
USER_AGENT = "CULTScope-imdb-downloader/0.1"


@dataclass(frozen=True)
class Dataset:
    key: str
    filename: str
    url: str


DATASETS: dict[str, Dataset] = {
    "basics": Dataset(
        key="basics",
        filename="title.basics.tsv.gz",
        url="https://datasets.imdbws.com/title.basics.tsv.gz",
    ),
    "ratings": Dataset(
        key="ratings",
        filename="title.ratings.tsv.gz",
        url="https://datasets.imdbws.com/title.ratings.tsv.gz",
    ),
}


class DownloadError(RuntimeError):
    """下载、校验或磁盘检查失败。"""


class _TransientError(DownloadError):
    """可重试的网络类错误。"""


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{size} B"


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_gzip(path: Path) -> None:
    """流式解压临时文件，确认 gzip 可完整读完（含 CRC 与结束标记）。

    只校验结构完整性，不保留解压内容，也不写入任何临时 TSV。
    该结果不能证明数据来自 IMDb 官方，仅证明本地文件未损坏。
    """
    try:
        with gzip.open(path, "rb") as handle:
            while handle.read(CHUNK_SIZE):
                pass
    except (OSError, EOFError, zlib.error) as exc:
        raise DownloadError(f"gzip 完整性校验失败：{path}：{exc}") from exc


def _unlink_quietly(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _read_chunk(response: http.client.HTTPResponse) -> bytes:
    """读取一块响应体；网络中断统一转成可重试异常。"""
    try:
        return response.read(CHUNK_SIZE)
    except (
        urllib.error.URLError,
        socket.timeout,
        TimeoutError,
        ConnectionError,
        http.client.HTTPException,
        ssl.SSLError,
    ) as exc:
        raise _TransientError(f"读取响应失败：{exc}") from exc


def _download_once(
    url: str,
    temp_path: Path,
    timeout: float,
    reserve_bytes: int,
) -> tuple[int, str]:
    """下载一次到临时文件，返回 (字节数, SHA-256)。

    网络类问题抛 `_TransientError`（可重试），其余问题抛 `DownloadError`。
    """
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code == 429 or 500 <= exc.code < 600:
            raise _TransientError(f"HTTP {exc.code}：{url}") from exc
        raise DownloadError(f"HTTP {exc.code}：{url}") from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
        raise _TransientError(f"连接失败：{exc}") from exc
    except ValueError as exc:
        raise DownloadError(f"无效的下载地址 {url}：{exc}") from exc

    with response:
        status = getattr(response, "status", 200)
        if status != 200:
            raise DownloadError(f"意外的 HTTP 状态 {status}：{url}")

        content_length = response.headers.get("Content-Length")
        expected_length = (
            int(content_length)
            if content_length is not None and content_length.isdigit()
            else None
        )
        try:
            free = shutil.disk_usage(temp_path.parent).free
        except OSError as exc:
            raise DownloadError(
                f"无法检查磁盘空间 {temp_path.parent}：{exc}"
            ) from exc
        if expected_length is not None and free < expected_length + reserve_bytes:
            raise DownloadError(
                f"磁盘空间不足：{temp_path.parent} 剩余 {_format_bytes(free)}，"
                f"本次约需 {_format_bytes(expected_length + reserve_bytes)}"
            )

        digest = hashlib.sha256()
        written = 0
        try:
            handle = temp_path.open("wb")
        except OSError as exc:
            raise DownloadError(f"无法写入临时文件 {temp_path}：{exc}") from exc
        with handle:
            while True:
                chunk = _read_chunk(response)
                if not chunk:
                    break
                try:
                    handle.write(chunk)
                except OSError as exc:
                    raise DownloadError(
                        f"写入临时文件失败 {temp_path}：{exc}"
                    ) from exc
                digest.update(chunk)
                written += len(chunk)
            try:
                handle.flush()
                os.fsync(handle.fileno())
            except OSError as exc:
                raise DownloadError(
                    f"刷新临时文件失败 {temp_path}：{exc}"
                ) from exc

    if written == 0:
        raise DownloadError(f"下载结果为空文件：{url}")
    if expected_length is not None and written != expected_length:
        raise _TransientError(
            f"下载不完整：期望 {expected_length} 字节，实际 {written} 字节"
        )

    streamed = digest.hexdigest()
    try:
        verified = _sha256_of(temp_path)
    except OSError as exc:
        raise DownloadError(f"回读临时文件失败 {temp_path}：{exc}") from exc
    if streamed != verified:
        # 仅证明本次写入与本地回读一致，不代表官方来源校验。
        raise DownloadError("SHA-256 校验失败：流式摘要与回读摘要不一致")
    return written, verified


def download_dataset(
    dataset: Dataset,
    output_dir: Path,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff: float = DEFAULT_BACKOFF,
    min_free_bytes: int = 0,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """下载单个数据集并原子替换目标文件，返回下载结果。"""
    output_dir = Path(output_dir)
    target = output_dir / dataset.filename
    result = {
        "dataset": dataset.key,
        "url": dataset.url,
        "target": str(target),
        "dry_run": dry_run,
        "bytes": 0,
        "sha256": "",
        "attempts": 0,
    }
    if dry_run:
        return result

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(output_dir).free
    except OSError as exc:
        raise DownloadError(f"无法准备输出目录 {output_dir}：{exc}") from exc
    if free < min_free_bytes:
        raise DownloadError(
            f"磁盘空间不足：{output_dir} 剩余 {_format_bytes(free)}，"
            f"要求至少保留 {_format_bytes(min_free_bytes)}"
        )

    attempt = 0
    while True:
        attempt += 1
        try:
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{dataset.filename}.", suffix=".part", dir=str(output_dir)
            )
        except OSError as exc:
            raise DownloadError(
                f"无法创建临时文件（目录 {output_dir}）：{exc}"
            ) from exc
        temp_path = Path(temp_name)
        try:
            os.close(descriptor)
        except OSError as exc:
            _unlink_quietly(temp_path)
            raise DownloadError(f"无法关闭临时文件 {temp_path}：{exc}") from exc

        try:
            written, digest = _download_once(
                dataset.url, temp_path, timeout, min_free_bytes
            )
            if dataset.filename.endswith(".gz"):
                _validate_gzip(temp_path)
        except _TransientError as exc:
            _unlink_quietly(temp_path)
            if attempt > retries:
                raise DownloadError(
                    f"{dataset.key} 下载失败（已尝试 {attempt} 次）：{exc}"
                ) from exc
            delay = min(backoff * (2 ** (attempt - 1)), MAX_BACKOFF)
            print(
                f"[重试] {dataset.key} 第 {attempt} 次失败：{exc}；"
                f"{delay:.1f}s 后重试",
                file=sys.stderr,
            )
            if delay > 0:
                sleep(delay)
            continue
        except Exception:
            _unlink_quietly(temp_path)
            raise

        try:
            os.replace(temp_path, target)
        except OSError as exc:
            _unlink_quietly(temp_path)
            raise DownloadError(f"无法写入目标文件 {target}：{exc}") from exc

        result.update(bytes=written, sha256=digest, attempts=attempt)
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="下载 IMDb 官方非商业数据集（流式、校验、原子替换）。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--dataset",
        choices=["basics", "ratings", "all"],
        default=None,
        help="要下载的数据集；不指定时不开始下载",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="原始文件保存目录（默认位于已忽略的 raw/imdb）",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="连接与单次读取超时（秒）",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help="网络失败后的最大重试次数",
    )
    parser.add_argument(
        "--backoff",
        type=float,
        default=DEFAULT_BACKOFF,
        help="指数退避的初始等待秒数",
    )
    parser.add_argument(
        "--min-free-gb",
        type=float,
        default=DEFAULT_MIN_FREE_GB,
        help="下载前要求保留的最小剩余空间（GB）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只显示下载计划，不创建目录或文件",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.dataset is None:
        print("未指定 --dataset，未开始下载。可选值：basics、ratings、all。", file=sys.stderr)
        parser.print_help()
        return 0

    if args.timeout <= 0:
        print("[错误] --timeout 必须大于 0", file=sys.stderr)
        return 2
    if args.retries < 0:
        print("[错误] --retries 不能为负数", file=sys.stderr)
        return 2
    if args.backoff < 0:
        print("[错误] --backoff 不能为负数", file=sys.stderr)
        return 2
    if args.min_free_gb < 0:
        print("[错误] --min-free-gb 不能为负数", file=sys.stderr)
        return 2

    keys = ["basics", "ratings"] if args.dataset == "all" else [args.dataset]
    min_free_bytes = int(args.min_free_gb * 1024**3)
    try:
        for key in keys:
            result = download_dataset(
                DATASETS[key],
                args.output_dir,
                timeout=args.timeout,
                retries=args.retries,
                backoff=args.backoff,
                min_free_bytes=min_free_bytes,
                dry_run=args.dry_run,
            )
            if args.dry_run:
                print(f"[dry-run] {key}：{result['url']} -> {result['target']}")
            else:
                print(
                    f"[完成] {key}：{result['target']}"
                    f"（{_format_bytes(result['bytes'])}，"
                    f"SHA-256 {result['sha256']}（本地完整性校验，非官方来源校验），"
                    f"尝试 {result['attempts']} 次）"
                )
    except DownloadError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("[dry-run] 未下载、未创建任何目录或文件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
