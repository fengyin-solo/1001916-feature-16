"""检修任务接口：维护检修任务单，覆盖批量派发、开始检修、确认完成等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    ActionResult,
    BatchActionPayload,
    BatchActionResult,
    CrewCapacity,
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
    crew: str | None = Query(default=None, description="按作业班组过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按任务编号、状态与作业班组过滤检修任务列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, crew=crew, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/crew-capacity", response_model=CrewCapacity)
def get_crew_capacity(crew: str = Query(description="作业班组名称")) -> CrewCapacity:
    """查询作业班组本计划周期的工时占用与剩余工时。"""
    crew = crew.strip()
    if not crew:
        raise HTTPException(status_code=400, detail="请提供作业班组名称")
    return CrewCapacity(**service.crew_capacity(crew))


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


@router.post("/batch-actions", response_model=BatchActionResult)
def run_batch(payload: BatchActionPayload) -> BatchActionResult:
    """整批派发或拉回：逐条校验逐条给结果，只拦截不满足条件的那一条。"""
    items = [item.model_dump() for item in payload.items]
    outcome = service.batch_act(payload.action, payload.crew, items)
    return BatchActionResult(**outcome)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条检修任务单执行派发任务、开始检修、确认完成；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
