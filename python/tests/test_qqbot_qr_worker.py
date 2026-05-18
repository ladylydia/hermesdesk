"""Tests for the desktop QQ Bot QR worker helpers."""

import unittest
from pathlib import Path
import sys


_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


class TestQqbotQrWorkerRetry(unittest.TestCase):
    def test_create_bind_task_retries_transient_failures(self):
        from qqbot_qr_worker import _create_bind_task_with_retry

        attempts = []
        progress = []
        sleeps = []

        def flaky_create():
            attempts.append(len(attempts) + 1)
            if len(attempts) < 3:
                raise OSError("temporary refusal")
            return "task-123", "aes-key"

        result = _create_bind_task_with_retry(
            flaky_create,
            write_progress=lambda payload: progress.append(payload),
            sleep=lambda seconds: sleeps.append(seconds),
            delays=(1.0, 2.0, 4.0, 6.0),
        )

        self.assertEqual(result, ("task-123", "aes-key"))
        self.assertEqual(len(attempts), 3)
        self.assertEqual(sleeps, [1.0, 2.0])
        self.assertTrue(any("正在连接 QQ 服务" in p.get("message", "") for p in progress))


if __name__ == "__main__":
    unittest.main()
