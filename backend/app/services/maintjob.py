"""检修任务业务规则：状态流转、字段校验、批量派发与班组工时占用口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "maintjob"
ACCEPT_MODULE = "accept"
REQUIRED_FIELDS = ["任务编号", "关联机组", "检修类型"]
STATUS_ORDER = ["待派发", "已派发", "检修中", "已完成"]
ACTION_RULES = {"派发任务": "已派发", "开始检修": "检修中", "确认完成": "已完成"}
BATCH_ACTIONS = {"派发任务": "已派发", "批量拉回": "待派发"}
NEGATIVE_ACTIONS = []

# 作业班组在一个计划周期内的可用工时上限；计划工时之和超过剩余工时的任务单要被拦下。
CREW_HOUR_BUDGET = 176.0
# 已派发、检修中的任务单仍占用班组工时；待派发（拉回后）与已完成的不再占用。
HOUR_OCCUPYING_STATUSES = {"已派发", "检修中"}
ACCEPTED_STATUS = "已通过"


def _to_hours(value: Any) -> float | None:
    """把计划工时解析成正数工时；空值、非数字、非正数都返回 None，由调用方拦截。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        hours = float(text)
    except ValueError:
        return None
    return hours if hours > 0 else None


class MaintjobService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        crew: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if crew:
            rows = [row for row in rows if (row.get("作业班组") or "") == crew]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self.present(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self.present(entry) if entry is not None else None

    def present(self, entry: dict[str, Any]) -> dict[str, Any]:
        """列表与详情共用的展示口径：任务状态始终以流转状态为准，作业班组取派发时记录值。"""
        view = dict(entry)
        view["任务状态"] = entry.get("status", "")
        view["作业班组"] = entry.get("作业班组") or ""
        return view

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["计划开始日"] = values.get("计划开始日")
        entry["计划工时"] = values.get("计划工时")
        entry["作业班组"] = values.get("作业班组") or ""
        entry["负责人"] = values.get("负责人") or ""
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self.present(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"检修任务单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于检修任务可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return self.present(entry), f"检修任务单已{action}"

    # ------------------------------------------------------------------
    # 批量派发 / 批量拉回
    # ------------------------------------------------------------------

    def batch_act(
        self,
        action: str,
        crew: str | None,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """整批执行动作：逐条校验、逐条给出结果，只拦截不满足条件的那一条。"""
        crew = (crew or "").strip()
        early = {
            "action": action,
            "crew": crew or None,
            "remaining_hours": None,
            "success_count": 0,
            "failed_count": 0,
            "results": [],
        }
        if action not in BATCH_ACTIONS:
            return {"ok": False, "message": f"动作「{action}」不支持批量执行", **early}
        if not crew:
            return {"ok": False, "message": "请先填写作业班组再提交", **early}

        # 同一张检修单在请求里重复出现时只保留最后一次提交内容。
        latest: dict[int, dict[str, Any]] = {}
        order: list[int] = []
        for item in items:
            try:
                entry_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            if entry_id not in latest:
                order.append(entry_id)
            latest[entry_id] = item.get("values") or {}
        if not order:
            return {"ok": False, "message": "请先勾选要处理的检修任务单", **early}

        results: list[dict[str, Any]] = []
        if action == "派发任务":
            remaining = self.crew_capacity(crew)["remaining_hours"]
            for entry_id in order:
                result, remaining = self._dispatch_one(entry_id, latest[entry_id], crew, remaining)
                results.append(result)
        else:
            for entry_id in order:
                results.append(self._pullback_one(entry_id, crew))
            remaining = self.crew_capacity(crew)["remaining_hours"]

        success = [item for item in results if item["ok"]]
        failed = [item for item in results if not item["ok"]]
        if success and failed:
            message = f"成功 {len(success)} 条，拦截 {len(failed)} 条，详见逐条结果"
        elif success:
            message = f"全部 {len(success)} 条检修任务单已{action}"
        else:
            message = f"{len(failed)} 条检修任务单均被拦截，未发生派发"
        return {
            "ok": bool(success),
            "action": action,
            "message": message,
            "crew": crew,
            "remaining_hours": round(remaining, 2),
            "success_count": len(success),
            "failed_count": len(failed),
            "results": results,
        }

    def _dispatch_one(
        self,
        entry_id: int,
        values: dict[str, Any],
        crew: str,
        remaining: float,
    ) -> tuple[dict[str, Any], float]:
        """派发单条任务单；返回（结果, 派发后班组剩余工时），被拦时剩余工时不变。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return self._fail(entry_id, None, f"检修任务单 {entry_id} 不存在或已归档"), remaining

        task_no = str(entry.get("任务编号") or "")
        if entry.get("status") != "待派发":
            return self._fail(entry_id, task_no, f"当前状态为「{entry.get('status')}」，只允许派发待派发的任务单"), remaining

        turbine = str(values.get("关联机组") or entry.get("关联机组") or "").strip()
        job_type = str(values.get("检修类型") or entry.get("检修类型") or "").strip()
        hours = _to_hours(values.get("计划工时") if values.get("计划工时") not in (None, "") else entry.get("计划工时"))

        # 按要求逐项拦截，并明确说明卡在哪一项。
        if not turbine:
            return self._fail(entry_id, task_no, "缺少关联机组，无法派发，请补录后重新提交"), remaining
        if not job_type:
            return self._fail(entry_id, task_no, "缺少检修类型，无法派发，请补录后重新提交"), remaining
        if hours is None:
            return self._fail(entry_id, task_no, "计划工时未填写或不是有效正数，无法派发"), remaining
        if hours > remaining:
            return (
                self._fail(
                    entry_id,
                    task_no,
                    f"计划工时 {hours:g} 超出作业班组「{crew}」剩余工时 {remaining:g}，请调整工时或改派其他班组",
                ),
                remaining,
            )

        entry["关联机组"] = turbine
        entry["检修类型"] = job_type
        entry["计划工时"] = int(hours) if hours.is_integer() else round(hours, 2)
        entry["作业班组"] = crew
        entry["status"] = "已派发"
        entry["pending"] = True
        entry["abnormal"] = False
        remaining -= hours
        return (
            {
                "id": entry_id,
                "task_no": task_no,
                "ok": True,
                "message": f"已派发给作业班组「{crew}」，占用工时 {hours:g}，班组剩余 {remaining:g}",
                "entry": self.present(entry),
            },
            remaining,
        )

    def _pullback_one(self, entry_id: int, crew: str) -> dict[str, Any]:
        """把已派发/检修中的任务单拉回待派发；验收通过的不允许拉回。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return self._fail(entry_id, None, f"检修任务单 {entry_id} 不存在或已归档")

        task_no = str(entry.get("任务编号") or "")
        if self._is_accepted(entry):
            return self._fail(entry_id, task_no, "关联验收单已验收通过，不允许批量拉回待派发")
        status = entry.get("status")
        if status == "待派发":
            return self._fail(entry_id, task_no, "当前已是待派发状态，无需拉回")
        if status == "已完成":
            return self._fail(entry_id, task_no, "任务已确认完成，不能拉回待派发")
        owner = entry.get("作业班组") or ""
        if owner and owner != crew:
            return self._fail(entry_id, task_no, f"该任务由作业班组「{owner}」持有，班组「{crew}」不能拉回")

        entry["status"] = "待派发"
        entry["pending"] = True
        return {
            "id": entry_id,
            "task_no": task_no,
            "ok": True,
            "message": f"已拉回待派发，释放占用工时，作业班组仍记录为「{owner or crew}」",
            "entry": self.present(entry),
        }

    def _is_accepted(self, entry: dict[str, Any]) -> bool:
        """关联验收单结论为「已通过」的检修任务单视为验收通过。"""
        task_no = str(entry.get("任务编号") or "")
        if not task_no:
            return False
        for accept_row in store.rows(ACCEPT_MODULE):
            if str(accept_row.get("关联任务") or "") == task_no and accept_row.get("status") == ACCEPTED_STATUS:
                return True
        return False

    def crew_capacity(self, crew: str) -> dict[str, Any]:
        """计算作业班组本周期的工时占用：只统计已派发/检修中任务单的有效计划工时。"""
        used = 0.0
        for row in store.rows(MODULE):
            if row.get("作业班组") != crew or row.get("status") not in HOUR_OCCUPYING_STATUSES:
                continue
            hours = _to_hours(row.get("计划工时"))
            if hours is not None:
                used += hours
        used = round(used, 2)
        return {
            "crew": crew,
            "total_hours": CREW_HOUR_BUDGET,
            "used_hours": used,
            "remaining_hours": round(CREW_HOUR_BUDGET - used, 2),
        }

    @staticmethod
    def _fail(entry_id: int, task_no: str | None, message: str) -> dict[str, Any]:
        return {"id": entry_id, "task_no": task_no, "ok": False, "message": message, "entry": None}
