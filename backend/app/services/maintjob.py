"""检修任务业务规则：状态流转、字段校验与筛选口径都收在这里。

批量派发的规则要点：
- 整批提交、逐条校验：某条缺关联机组或计划工时超出班组剩余工时，只拦这一条并写明原因；
- 同一张检修单在一批里重复提交时以最后一次填写内容为准；
- 已经验收通过的检修单不允许被批量拉回待派发；
- 列表与详情都走 present_entry 同一口径输出，作业班组等字段保持一致。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "maintjob"
ACCEPT_MODULE = "accept"
REQUIRED_FIELDS = ["任务编号", "关联机组", "检修类型"]
STATUS_ORDER = ["待派发", "已派发", "检修中", "已完成"]
ACTION_RULES = {"派发任务": "已派发", "开始检修": "检修中", "确认完成": "已完成"}
NEGATIVE_ACTIONS = []

# 班组可排产工时上限：某班组全部「已派发/检修中」检修单的计划工时之和不能超过这个值
TEAM_WORK_HOUR_CAP = 40
ACTIVE_STATUSES = ["已派发", "检修中"]
# 预置班组目录（实际项目里会来自组织架构接口）
KNOWN_TEAMS = ["机械一班", "机械二班", "电气一班", "电气二班"]

BATCH_ACTION_DISPATCH = "派发任务"
BATCH_ACTION_PULLBACK = "拉回待派发"


def _parse_hours(value: Any) -> float | None:
    """把计划工时解析成非负数字；空值、非数字或负数都返回 None，由调用方决定口径。"""
    if value is None or str(value).strip() == "":
        return None
    try:
        hours = float(value)
    except (TypeError, ValueError):
        return None
    return hours if hours >= 0 else None


class MaintjobService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self.present_entry(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self.present_entry(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        if str(values.get("计划开始日") or "").strip():
            entry["计划开始日"] = values["计划开始日"]
        if str(values.get("计划工时") or "").strip():
            entry["计划工时"] = values["计划工时"]
        if str(values.get("作业班组") or "").strip():
            entry["作业班组"] = values["作业班组"]
        if str(values.get("负责人") or "").strip():
            entry["负责人"] = values["负责人"]
        self._apply_status(entry, STATUS_ORDER[0])
        rows.append(entry)
        return self.present_entry(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"检修任务单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于检修任务可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        # 单条派发同样走容量校验：显式带了作业班组/计划工时时与批量派发同一把尺子，
        # 不带时维持原有快速派发行为，避免把旧入口一并卡死。
        if action == BATCH_ACTION_DISPATCH and (entry.get("作业班组") or entry.get("计划工时")):
            presented, message = self._dispatch_one(entry, str(entry.get("作业班组") or ""), entry.get("计划工时"))
            if presented is None:
                return None, message
            return presented, message

        self._apply_status(entry, target)
        return self.present_entry(entry), f"检修任务单已{action}"

    # ------------------------------------------------------------------
    # 批量派发 / 批量拉回
    # ------------------------------------------------------------------
    def run_batch_action(
        self,
        action: str,
        team: str | None,
        items: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], str]:
        """整批提交检修单，逐条给出派发结果。

        返回 (results, top_message)；results 里每条含 ok/message/entry，
        卡在哪一项就写在哪一条的 message 中，其余条目照常派发。
        """
        action = str(action or "").strip() or BATCH_ACTION_DISPATCH
        if action not in (BATCH_ACTION_DISPATCH, BATCH_ACTION_PULLBACK):
            raise ValueError(f"动作「{action}」不属于批量派发可执行范围")
        if not items:
            raise ValueError("请先勾选需要处理的检修任务单")
        team = str(team or "").strip()
        if action == BATCH_ACTION_DISPATCH and not team:
            raise ValueError("批量派发需指定作业班组")

        # 同一张检修单重复提交：按 id 去重，只保留最后一次填写的检修类型与计划工时
        latest: dict[int, dict[str, Any]] = {}
        for item in items:
            try:
                entry_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            latest[entry_id] = item

        if action == BATCH_ACTION_DISPATCH:
            process = lambda entry, item: self._dispatch_one(
                entry, team, item.get("计划工时"), item.get("检修类型")
            )
        else:
            process = lambda entry, item: self._pullback_one(entry)

        results: list[dict[str, Any]] = []
        for entry_id, item in latest.items():
            entry = store.find(MODULE, entry_id)
            if entry is None:
                results.append({"id": entry_id, "任务编号": None, "ok": False,
                                "message": f"检修任务单 {entry_id} 不存在或已归档", "entry": None})
                continue
            presented, message = process(entry, item)
            results.append({
                "id": entry_id,
                "任务编号": entry.get("任务编号"),
                "ok": presented is not None,
                "message": message,
                "entry": presented,
            })

        success = sum(1 for row in results if row["ok"])
        failed = len(results) - success
        if action == BATCH_ACTION_DISPATCH:
            verb = "派发"
        else:
            verb = "拉回待派发"
        if failed == 0:
            top_message = f"批量{verb}完成，共成功 {success} 条"
        elif success == 0:
            top_message = f"批量{verb}未成功：{failed} 条全部被拦下，请按逐条提示处理"
        else:
            top_message = f"批量{verb}完成：成功 {success} 条，{failed} 条被拦下"
        return results, top_message

    def _dispatch_one(
        self,
        entry: dict[str, Any],
        team: str,
        raw_hours: Any,
        job_type: Any = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """派发单条检修单的完整校验链；任何一项不过都只拦当前这一条。"""
        code = str(entry.get("任务编号") or entry.get("id", 0))

        if not str(entry.get("关联机组") or "").strip():
            return None, f"{code} 缺少关联机组，无法派发"
        if entry.get("status") != STATUS_ORDER[0]:
            return None, f"{code} 当前为「{entry.get('status')}」，仅待派发的检修单可派发"

        job_type = str(job_type or "").strip() or str(entry.get("检修类型") or "").strip()
        if not job_type:
            return None, f"{code} 缺少检修类型，无法派发"

        hours = _parse_hours(raw_hours if raw_hours is not None else entry.get("计划工时"))
        if hours is None:
            return None, f"{code} 计划工时缺失或不是有效数字"

        used, remaining = self.team_capacity(team)
        if hours > remaining + 1e-9:
            return None, (
                f"{code} 计划工时 {hours:g} 超出作业班组「{team}」剩余工时"
                f"（已排 {used:g}/{TEAM_WORK_HOUR_CAP:g}，剩余 {remaining:g}）"
            )

        entry["检修类型"] = job_type
        entry["计划工时"] = hours
        entry["作业班组"] = team
        self._apply_status(entry, "已派发")
        return self.present_entry(entry), f"{code} 已派发给「{team}」，剩余工时 {max(remaining - hours, 0):g}"

    def _pullback_one(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """把一条已派发检修单拉回待派发；验收通过的单子在这里被拦下。"""
        code = str(entry.get("任务编号") or entry.get("id", 0))
        if self.is_accepted(entry):
            return None, f"{code} 已验收通过，不允许批量拉回待派发"
        status = entry.get("status")
        if status == "检修中":
            return None, f"{code} 正在检修中，需完成检修并验收后再处理，不能拉回待派发"
        if status == "待派发":
            return self.present_entry(entry), f"{code} 本来就处于待派发，无需重复拉回"
        if status not in ("已派发", "已完成"):
            return None, f"{code} 当前为「{status}」，不能拉回待派发"
        entry["作业班组"] = ""
        self._apply_status(entry, "待派发")
        return self.present_entry(entry), f"{code} 已拉回待派发，原班组占用工时已释放"

    # ------------------------------------------------------------------
    # 班组工时与验收联动
    # ------------------------------------------------------------------
    def team_capacity(self, team: str) -> tuple[float, float]:
        """返回某班组已排工时与剩余工时；只有已派发/检修中的单子占用容量。"""
        used = 0.0
        for row in store.rows(MODULE):
            if row.get("作业班组") == team and row.get("status") in ACTIVE_STATUSES:
                hours = _parse_hours(row.get("计划工时"))
                if hours is not None:
                    used += hours
        return used, TEAM_WORK_HOUR_CAP - used

    def list_teams(self) -> list[dict[str, Any]]:
        """给批量派发下拉框用：班组目录 + 当前已排/剩余工时。"""
        names = list(KNOWN_TEAMS)
        for row in store.rows(MODULE):
            name = str(row.get("作业班组") or "").strip()
            if name and name not in names:
                names.append(name)
        teams = []
        for name in names:
            used, remaining = self.team_capacity(name)
            teams.append({
                "作业班组": name,
                "工时上限": TEAM_WORK_HOUR_CAP,
                "已排工时": used,
                "剩余工时": remaining,
            })
        return teams

    def is_accepted(self, entry: dict[str, Any]) -> bool:
        """验收单「已通过」且关联任务指向该检修单（按任务编号匹配）即视为验收通过。"""
        code = str(entry.get("任务编号") or "").strip()
        if not code:
            return False
        for accept in store.rows(ACCEPT_MODULE):
            linked = str(accept.get("关联任务") or "").strip()
            if accept.get("status") == "已通过" and linked == code:
                return True
        return False

    # ------------------------------------------------------------------
    # 输出口径：列表与详情共用同一份字段
    # ------------------------------------------------------------------
    def present_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """统一展示口径：作业班组等字段列表、详情、批量结果都从这里出。"""
        view = dict(entry)
        team = str(view.get("作业班组") or "").strip()
        view["作业班组"] = team
        view["任务状态"] = view.get("status")
        hours = _parse_hours(view.get("计划工时"))
        if hours is not None:
            view["计划工时"] = hours
        return view

    def _apply_status(self, entry: dict[str, Any], status: str) -> None:
        """状态流转时同步内部 status 与展示用「任务状态」，保证两个字段不打架。"""
        entry["status"] = status
        entry["任务状态"] = status
        entry["pending"] = status != STATUS_ORDER[-1]
        entry["abnormal"] = False
