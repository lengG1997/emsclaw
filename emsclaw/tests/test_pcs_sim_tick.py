"""task-service pcs_sim_tick 任务 — HTTP 调用 backend tick 端点 测试。"""
import sys
from pathlib import Path

_TS = Path(__file__).resolve().parent.parent / "task-service"
if str(_TS) not in sys.path:
    sys.path.insert(0, str(_TS))

from unittest.mock import patch, MagicMock

import pytest


def test_pcs_sim_tick_calls_backend(monkeypatch):
    # 模拟 settings
    from app import tasks as t
    monkeypatch.setattr(t.settings, "chat_service_url", "http://backend:8000")
    monkeypatch.setattr(t.settings, "chat_service_api_key", "secret")

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"code": 0, "data": {"ticked": 1, "ts": 1000}}
    fake_resp.text = ""

    with patch("app.tasks.httpx.Client") as ClientMock:
        ClientMock.return_value.__enter__.return_value.post.return_value = fake_resp
        t.pcs_sim_tick()
        # 断言调了 POST /api/v1/pcs/sim/tick 且带 X-API-Key
        call = ClientMock.return_value.__enter__.return_value.post
        call.assert_called_once()
        args, kwargs = call.call_args
        assert "/api/v1/pcs/sim/tick" in args[0]
        assert kwargs["headers"]["X-API-Key"] == "secret"


def test_pcs_sim_tick_handles_error(monkeypatch, capsys):
    from app import tasks as t
    monkeypatch.setattr(t.settings, "chat_service_url", "http://backend:8000")
    monkeypatch.setattr(t.settings, "chat_service_api_key", "")

    with patch("app.tasks.httpx.Client") as ClientMock:
        ClientMock.return_value.__enter__.return_value.post.side_effect = Exception("boom")
        # 不应抛错
        t.pcs_sim_tick()
