"""ApprovalMapper — 纯 ORM 持久化层测试(sqlite 全栈)。

验证 insert / find_by_interrupt / find_by_id / update / list_page 的 SQL 行为。
"""
import pytest

from emsclaw_backend.db.models import ApprovalRecord
from emsclaw_backend.mapper.approval_mapper import ApprovalMapper


def _make_record(**overrides) -> ApprovalRecord:
    base = dict(
        id="APR-AAAA0001",
        session_id="sess-1",
        thread_id="thr-1",
        interrupt_id="intr-001",
        tool_name="create_device",
        tool_args={"name": "X", "device_type": "battery"},
        tool_call_id=None,
        tool_result=None,
        parent_agent="DeepAgent",
        subagent_type="device_management",
        subagent_instance_id="device_management_abcd1234",
        initiator_user_id="user-1",
        approver_user_id=None,
        decision=None,
        original_request_message="帮我创建一个电池设备",
        auto=False,
        status="pending",
        created_at=1000,
        decided_at=None,
    )
    base.update(overrides)
    return ApprovalRecord(**base)


def test_insert_and_find_by_interrupt(sqlite_approval_db):
    m = ApprovalMapper()
    inserted = m.insert(_make_record())
    found = m.find_by_interrupt("intr-001")
    assert found is not None
    assert found.id == inserted.id
    assert found.tool_name == "create_device"
    assert found.subagent_type == "device_management"
    assert found.status == "pending"


def test_find_by_interrupt_returns_none_when_missing(sqlite_approval_db):
    assert ApprovalMapper().find_by_interrupt("nope") is None


def test_find_by_id(sqlite_approval_db):
    m = ApprovalMapper()
    m.insert(_make_record(id="APR-ID1", interrupt_id="i-a"))
    assert m.find_by_id("APR-ID1") is not None
    assert m.find_by_id("APR-NOPE") is None


def test_update_marks_decided(sqlite_approval_db):
    m = ApprovalMapper()
    rec = m.insert(_make_record())
    rec.decision = "approve"
    rec.approver_user_id = "user-2"
    rec.auto = False
    rec.status = "decided"
    rec.decided_at = 2000
    updated = m.update(rec)
    assert updated.decision == "approve"
    assert updated.approver_user_id == "user-2"
    assert updated.status == "decided"
    assert updated.decided_at == 2000
    # 再读一次确认持久化
    refetched = m.find_by_interrupt(rec.interrupt_id)
    assert refetched.decision == "approve"
    assert refetched.status == "decided"


def test_list_page_pagination(sqlite_approval_db):
    m = ApprovalMapper()
    for i in range(25):
        m.insert(_make_record(
            id=f"APR-{i:04d}",
            interrupt_id=f"intr-{i:04d}",
            created_at=1000 + i,
        ))
    page1, total = m.list_page(page=1, page_size=10)
    assert total == 25
    assert len(page1) == 10
    # 按 created_at desc,第一条是最新
    assert page1[0].created_at == 1024
    assert page1[-1].created_at == 1015
    page3, _ = m.list_page(page=3, page_size=10)
    assert len(page3) == 5  # 25 - 20


def test_list_page_filters(sqlite_approval_db):
    m = ApprovalMapper()
    m.insert(_make_record(id="APR-P1", interrupt_id="i-p1",
                          status="pending", session_id="s-A", initiator_user_id="u-A"))
    m.insert(_make_record(id="APR-D1", interrupt_id="i-d1",
                          status="decided", session_id="s-A", initiator_user_id="u-A",
                          decision="approve"))
    m.insert(_make_record(id="APR-P2", interrupt_id="i-p2",
                          status="pending", session_id="s-B", initiator_user_id="u-B"))

    pending, total = m.list_page(status="pending")
    assert total == 2
    assert {r.id for r in pending} == {"APR-P1", "APR-P2"}

    sess_a, total = m.list_page(session_id="s-A")
    assert total == 2
    assert {r.id for r in sess_a} == {"APR-P1", "APR-D1"}

    by_user, total = m.list_page(initiator_user_id="u-B")
    assert total == 1
    assert by_user[0].id == "APR-P2"


def test_list_page_empty(sqlite_approval_db):
    rows, total = ApprovalMapper().list_page()
    assert rows == []
    assert total == 0


def test_create_pending_with_tool_call_id(sqlite_approval_db):
    """ApprovalService.create_pending 应写入 tool_call_id(供后续出参回填关联)。"""
    from emsclaw_backend.service.approval_service import ApprovalService
    svc = ApprovalService()
    rec = svc.create_pending(
        session_id="sess-1",
        thread_id="thr-1",
        interrupt_id="intr-cp",
        tool_name="create_device",
        tool_args={"name": "BAT"},
        tool_call_id="call_abc123",
        parent_agent="DeepAgent",
        subagent_type="device_management",
        subagent_instance_id="device_management_abcd1234",
        initiator_user_id="user-1",
        original_request_message="建电池",
    )
    assert rec.id
    assert rec.tool_call_id == "call_abc123"
    assert rec.status == "pending"
    assert rec.tool_result is None
    found = ApprovalMapper().find_by_interrupt("intr-cp")
    assert found is not None
    assert found.tool_call_id == "call_abc123"
    assert found.tool_result is None


def test_attach_tool_result(sqlite_approval_db):
    """attach_tool_result 应把工具出参回填到对应 interrupt_id 的记录。"""
    from emsclaw_backend.service.approval_service import ApprovalService
    m = ApprovalMapper()
    m.insert(_make_record(interrupt_id="intr-ar"))
    svc = ApprovalService()
    updated = svc.attach_tool_result("intr-ar", '{"ok": true, "device_id": "D1"}')
    assert updated is not None
    assert updated.tool_result == '{"ok": true, "device_id": "D1"}'
    # 再次读取确认持久化
    refetched = m.find_by_interrupt("intr-ar")
    assert refetched.tool_result == '{"ok": true, "device_id": "D1"}'


def test_attach_tool_result_missing_interrupt(sqlite_approval_db):
    """不存在的 interrupt_id 应返回 None,不抛异常。"""
    from emsclaw_backend.service.approval_service import ApprovalService
    assert ApprovalService().attach_tool_result("nope", "x") is None
