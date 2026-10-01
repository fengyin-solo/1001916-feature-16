"""检修任务接口：维护检修任务单，覆盖批量派发、开始检修、确认完成等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    ActionResult,
    BatchActionPayload,
    BatchActionResult,
    BatchResultItem,
    EntryPayload,
    PageResult,
)
from app.services.maintjob import MaintjobService

router = APIRouter(prefix="/api/maintjob", tags=["检修任务"])

service = MaintjobService()

LIST_FIELDS = ["任务编号", "关联机组", "检修类型", "计划开始日", "计划工时", "作业班组", "负责人", "任务状态"]
STATUSES = ["待派发", "已派发", "检修中", "已完成"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按任务编号检索"),
    status: str | None = Query(default=None, description="待派发、已派发、检修中、已完成"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按任务编号与状态过滤检修任务列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/teams")
def list_teams() -> dict[str, Any]:
    """班组目录及其已排/剩余工时，供批量派发时选择作业班组与提示容量。"""
    teams = service.list_teams()
    return {"total": len(teams), "items": teams}


@router.post("/batch", response_model=BatchActionResult)
def run_batch(payload: BatchActionPayload) -> BatchActionResult:
    """作业班组整批派发：勾选多条检修单一起提交，逐条返回派发结果。

    某条缺关联机组或计划工时超出班组剩余工时时只拦这一条并说明卡在哪一项，
    其余条目照常派发；同一检修单重复提交只保留最后一次的结果。
    """
    raw_items = [
        {"id": item.id, "检修类型": item.检修类型, "计划工时": item.计划工时}
        for item in payload.items
    ]
    try:
        results, top_message = service.run_batch_action(payload.action, payload.作业班组, raw_items)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    action = str(payload.action or "派发任务").strip() or "派发任务"
    success = sum(1 for row in results if row["ok"])
    return BatchActionResult(
        ok=success > 0,
        message=top_message,
        action=action,
        success_count=success,
        failed_count=len(results) - success,
        results=[BatchResultItem(**row) for row in results],
    )


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出检修任务清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "maintjob", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条检修任务单明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"检修任务单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条检修任务单，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="检修任务单已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条检修任务单执行派发任务、开始检修、确认完成；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
