"""IMDb 下载器测试：全部使用本地模拟 HTTP 服务，不访问真实网络。"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import http.server
import io
import os
import sys
import tempfile
import threading
import unittest
from collections import namedtuple
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import scripts.download_imdb as download_module  # noqa: E402
from scripts.download_imdb import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    Dataset,
    DownloadError,
    download_dataset,
    main,
)


def _gzip_bytes(data: bytes) -> bytes:
    """生成真实 gzip 数据，供模拟服务器返回。"""
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as handle:
        handle.write(data)
    return buffer.getvalue()


PAYLOAD_BASICS = _gzip_bytes(b"tconst\ttitleType\n" + b"tt0000001\tmovie\n" * 128)
PAYLOAD_RATINGS = _gzip_bytes(b"tconst\taverageRating\n" + b"tt0000001\t8.7\n" * 64)

DiskUsage = namedtuple("DiskUsage", ["total", "used", "free"])


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        server: "MockHttpServer" = self.server.mock_server  # type: ignore[attr-defined]
        server.requests.append(self.path)
        remaining = server.failures.get(self.path, 0)
        if remaining > 0:
            server.failures[self.path] = remaining - 1
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"server error")
            return

        payload = server.payloads.get(self.path)
        if payload is None:
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.path in server.truncate_paths:
            self.wfile.write(payload[: max(1, len(payload) // 2)])
            self.wfile.flush()
            self.close_connection = True
            return
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass


class MockHttpServer:
    def __init__(self) -> None:
        self.payloads: dict[str, bytes] = {}
        self.failures: dict[str, int] = {}
        self.truncate_paths: set[str] = set()
        self.requests: list[str] = []
        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.mock_server = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def url_for(self, filename: str) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}/{filename}"

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


class DownloadImdbTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.output_dir = self.root / "imdb"
        self.server = MockHttpServer()
        self.addCleanup(self.server.close)
        self.server.payloads["/title.basics.tsv.gz"] = PAYLOAD_BASICS
        self.server.payloads["/title.ratings.tsv.gz"] = PAYLOAD_RATINGS

    def _dataset(self, key: str = "basics") -> Dataset:
        filename = f"title.{key}.tsv.gz"
        return Dataset(key, filename, self.server.url_for(filename))

    def _run(self, dataset: Dataset, **overrides) -> dict:
        params = {
            "timeout": 5.0,
            "retries": 0,
            "backoff": 0.0,
            "min_free_bytes": 0,
            "dry_run": False,
        }
        params.update(overrides)
        return download_dataset(dataset, self.output_dir, **params)

    def _parts(self) -> list[Path]:
        if not self.output_dir.exists():
            return []
        return [entry for entry in self.output_dir.iterdir() if entry.name.endswith(".part")]

    # 1. 正常下载：内容、SHA-256、原子替换、无临时残留
    def test_downloads_and_writes_atomically(self) -> None:
        result = self._run(self._dataset())
        target = self.output_dir / "title.basics.tsv.gz"
        self.assertEqual(target.read_bytes(), PAYLOAD_BASICS)
        self.assertEqual(result["sha256"], hashlib.sha256(PAYLOAD_BASICS).hexdigest())
        self.assertEqual(result["bytes"], len(PAYLOAD_BASICS))
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(self._parts(), [])
        self.assertEqual(self.server.requests, ["/title.basics.tsv.gz"])

    # 2. dry-run 不创建目录或文件、不发请求
    def test_dry_run_creates_nothing(self) -> None:
        result = self._run(self._dataset(), dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertFalse(self.output_dir.exists())
        self.assertEqual(self.server.requests, [])

    # 3. 成功后替换已有旧文件
    def test_success_replaces_existing_file(self) -> None:
        self.output_dir.mkdir(parents=True)
        target = self.output_dir / "title.basics.tsv.gz"
        target.write_bytes(b"old-content")
        self._run(self._dataset())
        self.assertEqual(target.read_bytes(), PAYLOAD_BASICS)
        self.assertEqual(self._parts(), [])

    # 4. 永不成功时保留旧文件并清理临时文件
    def test_failure_keeps_existing_file(self) -> None:
        self.output_dir.mkdir(parents=True)
        target = self.output_dir / "title.basics.tsv.gz"
        target.write_bytes(b"old-content")
        self.server.failures["/title.basics.tsv.gz"] = 99
        with self.assertRaises(DownloadError):
            self._run(self._dataset())
        self.assertEqual(target.read_bytes(), b"old-content")
        self.assertEqual(self._parts(), [])
        self.assertEqual(len(self.server.requests), 1)

    # 5. 有限重试后成功
    def test_retries_then_succeeds(self) -> None:
        self.server.failures["/title.basics.tsv.gz"] = 2
        result = self._run(self._dataset(), retries=3)
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(len(self.server.requests), 3)
        self.assertEqual(
            (self.output_dir / "title.basics.tsv.gz").read_bytes(), PAYLOAD_BASICS
        )

    # 6. 重试有上限
    def test_retries_are_bounded(self) -> None:
        self.server.failures["/title.basics.tsv.gz"] = 99
        with self.assertRaises(DownloadError):
            self._run(self._dataset(), retries=2)
        self.assertEqual(len(self.server.requests), 3)
        self.assertFalse((self.output_dir / "title.basics.tsv.gz").exists())

    # 7. 响应被截断时判定失败，不写入正式文件
    def test_truncated_download_is_discarded(self) -> None:
        self.output_dir.mkdir(parents=True)
        target = self.output_dir / "title.basics.tsv.gz"
        target.write_bytes(b"old-content")
        self.server.truncate_paths.add("/title.basics.tsv.gz")
        with self.assertRaises(DownloadError):
            self._run(self._dataset())
        self.assertEqual(target.read_bytes(), b"old-content")
        self.assertEqual(self._parts(), [])

    # 8. SHA-256 回读校验失败时不覆盖旧文件
    def test_sha256_mismatch_is_rejected(self) -> None:
        self.output_dir.mkdir(parents=True)
        target = self.output_dir / "title.basics.tsv.gz"
        target.write_bytes(b"old-content")
        with mock.patch.object(download_module, "_sha256_of", return_value="deadbeef"):
            with self.assertRaises(DownloadError):
                self._run(self._dataset())
        self.assertEqual(target.read_bytes(), b"old-content")
        self.assertEqual(self._parts(), [])

    # 9. 下载前磁盘空间不足：不发请求、不写文件
    def test_insufficient_disk_space_fails_before_request(self) -> None:
        with mock.patch.object(
            download_module.shutil, "disk_usage", return_value=DiskUsage(0, 0, 10)
        ):
            with self.assertRaises(DownloadError):
                self._run(self._dataset(), min_free_bytes=100)
        self.assertEqual(self.server.requests, [])
        self.assertFalse((self.output_dir / "title.basics.tsv.gz").exists())
        self.assertEqual(self._parts(), [])

    # 10. 响应头 Content-Length 超过剩余空间时中止
    def test_content_length_exceeding_free_space_is_rejected(self) -> None:
        with mock.patch.object(
            download_module.shutil, "disk_usage", return_value=DiskUsage(0, 0, 10)
        ):
            with self.assertRaises(DownloadError):
                self._run(self._dataset())
        self.assertFalse((self.output_dir / "title.basics.tsv.gz").exists())
        self.assertEqual(self._parts(), [])

    # 11. --help 退出码为 0
    def test_cli_help_exits_zero(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                main(["--help"])
        self.assertEqual(caught.exception.code, 0)

    # 12. 不指定 --dataset 时不下载
    def test_cli_without_dataset_does_not_download(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["--output-dir", str(self.output_dir)])
        self.assertEqual(code, 0)
        self.assertFalse(self.output_dir.exists())
        self.assertIn("未指定 --dataset", stderr.getvalue())

    # 13. CLI --dry-run 不创建目录
    def test_cli_dry_run_creates_nothing(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(
                ["--dataset", "basics", "--dry-run", "--output-dir", str(self.output_dir)]
            )
        self.assertEqual(code, 0)
        self.assertFalse(self.output_dir.exists())
        self.assertIn("[dry-run]", stdout.getvalue())
        self.assertEqual(self.server.requests, [])

    # 14. CLI 下载失败返回非零退出码
    def test_cli_failure_returns_nonzero(self) -> None:
        self.server.failures["/title.basics.tsv.gz"] = 99
        stderr = io.StringIO()
        with mock.patch.dict(
            download_module.DATASETS, {"basics": self._dataset("basics")}
        ):
            with contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "--dataset",
                        "basics",
                        "--retries",
                        "0",
                        "--backoff",
                        "0",
                        "--output-dir",
                        str(self.output_dir),
                    ]
                )
        self.assertEqual(code, 1)
        self.assertIn("[错误]", stderr.getvalue())

    # 15. CLI 成功下载并输出 SHA-256
    def test_cli_success_downloads_dataset(self) -> None:
        stdout = io.StringIO()
        with mock.patch.dict(
            download_module.DATASETS, {"basics": self._dataset("basics")}
        ):
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--dataset",
                        "basics",
                        "--retries",
                        "0",
                        "--output-dir",
                        str(self.output_dir),
                    ]
                )
        self.assertEqual(code, 0)
        self.assertEqual(
            (self.output_dir / "title.basics.tsv.gz").read_bytes(), PAYLOAD_BASICS
        )
        self.assertIn(hashlib.sha256(PAYLOAD_BASICS).hexdigest(), stdout.getvalue())

    # 16. --dataset all 依次下载两个数据集
    def test_cli_all_downloads_both_datasets(self) -> None:
        stdout = io.StringIO()
        with mock.patch.dict(
            download_module.DATASETS,
            {
                "basics": self._dataset("basics"),
                "ratings": self._dataset("ratings"),
            },
        ):
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--dataset",
                        "all",
                        "--retries",
                        "0",
                        "--output-dir",
                        str(self.output_dir),
                    ]
                )
        self.assertEqual(code, 0)
        self.assertEqual(
            (self.output_dir / "title.basics.tsv.gz").read_bytes(), PAYLOAD_BASICS
        )
        self.assertEqual(
            (self.output_dir / "title.ratings.tsv.gz").read_bytes(), PAYLOAD_RATINGS
        )

    # 17. 默认输出目录位于被忽略的 raw/imdb
    def test_default_output_dir(self) -> None:
        self.assertEqual(
            DEFAULT_OUTPUT_DIR, BACKEND_DIR / "data" / "raw" / "imdb"
        )

    # 18. 目录创建失败转换为 DownloadError
    def test_directory_creation_failure_is_reported(self) -> None:
        def failing_mkdir(self_path, *args, **kwargs):
            raise OSError("injected mkdir failure")

        with mock.patch.object(Path, "mkdir", failing_mkdir):
            with self.assertRaises(DownloadError) as caught:
                self._run(self._dataset())
        self.assertIn("输出目录", str(caught.exception))
        self.assertFalse((self.output_dir / "title.basics.tsv.gz").exists())

    # 19. 临时文件创建失败转换为 DownloadError
    def test_temp_file_creation_failure_is_reported(self) -> None:
        with mock.patch.object(
            download_module.tempfile,
            "mkstemp",
            side_effect=OSError("injected mkstemp failure"),
        ):
            with self.assertRaises(DownloadError) as caught:
                self._run(self._dataset())
        self.assertIn("临时文件", str(caught.exception))
        self.assertFalse((self.output_dir / "title.basics.tsv.gz").exists())

    # 20. 磁盘写入失败：保留旧文件并清理临时文件
    def test_disk_write_failure_keeps_existing_file(self) -> None:
        self.output_dir.mkdir(parents=True)
        target = self.output_dir / "title.basics.tsv.gz"
        target.write_bytes(PAYLOAD_RATINGS)
        before = target.read_bytes()
        real_open = Path.open

        def fake_open(path_self, *args, **kwargs):
            if path_self.name.endswith(".part") and args and args[0] == "wb":
                raise OSError("injected disk write failure")
            return real_open(path_self, *args, **kwargs)

        with mock.patch.object(Path, "open", fake_open):
            with self.assertRaises(DownloadError) as caught:
                self._run(self._dataset())
        self.assertIn("临时文件", str(caught.exception))
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(self._parts(), [])

    # 21. fsync 失败：保留旧文件并清理临时文件
    def test_fsync_failure_keeps_existing_file(self) -> None:
        self.output_dir.mkdir(parents=True)
        target = self.output_dir / "title.basics.tsv.gz"
        target.write_bytes(PAYLOAD_RATINGS)
        before = target.read_bytes()
        with mock.patch.object(
            download_module.os,
            "fsync",
            side_effect=OSError("injected fsync failure"),
        ):
            with self.assertRaises(DownloadError) as caught:
                self._run(self._dataset())
        self.assertIn("刷新临时文件", str(caught.exception))
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(self._parts(), [])

    # 22. 无效 gzip：拒绝替换，保留旧文件
    def test_invalid_gzip_keeps_existing_file(self) -> None:
        self.output_dir.mkdir(parents=True)
        target = self.output_dir / "title.basics.tsv.gz"
        target.write_bytes(PAYLOAD_RATINGS)
        before = target.read_bytes()
        self.server.payloads["/title.basics.tsv.gz"] = b"<html>not gzip</html>" * 32
        with self.assertRaises(DownloadError) as caught:
            self._run(self._dataset())
        self.assertIn("gzip", str(caught.exception))
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(self._parts(), [])

    # 23. gzip 截断：CRC/结束标记检查失败，保留旧文件
    def test_truncated_gzip_keeps_existing_file(self) -> None:
        self.output_dir.mkdir(parents=True)
        target = self.output_dir / "title.basics.tsv.gz"
        target.write_bytes(PAYLOAD_RATINGS)
        before = target.read_bytes()
        self.server.payloads["/title.basics.tsv.gz"] = PAYLOAD_BASICS[:-10]
        with self.assertRaises(DownloadError) as caught:
            self._run(self._dataset())
        self.assertIn("gzip", str(caught.exception))
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(self._parts(), [])

    # 24. 无旧文件时 gzip 无效：不留下正式输出或临时文件
    def test_invalid_gzip_leaves_no_outputs(self) -> None:
        self.server.payloads["/title.basics.tsv.gz"] = b"fake gzip payload"
        with self.assertRaises(DownloadError):
            self._run(self._dataset())
        self.assertFalse((self.output_dir / "title.basics.tsv.gz").exists())
        self.assertEqual(self._parts(), [])


if __name__ == "__main__":
    unittest.main()
