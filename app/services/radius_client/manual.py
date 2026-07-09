"""
ManualRadiusClient — نسخة المرحلة 1.

كل العمليات التعديلية تُسجَّل في radius_pending_actions، ولا يتصل بأي API.
المدير يفتح /admin/cards/pending أو /admin/users/pending، ينفّذ العملية يدويًا،
ثم يضع علامة "منفّذ".

الـ Live في المرحلة 2 يستبدل هذا الملف بـ live.py بدون أي تغيير في باقي الكود.
"""
from __future__ import annotations

import json
from typing import Any

from app import legacy

from .base import RadiusClient
from .dtos import PendingAction, Profile, Result, Session, UsageSnapshot


def _now_iso() -> str:
    return legacy.now_local().isoformat(sep=" ", timespec="seconds")


def _json_dumps(data: Any) -> str:
    if not data:
        return "{}"
    try:
        return json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return "{}"


def _json_loads(text: str) -> dict:
    if not text:
        return {}
    try:
        return json.loads(text) or {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


class ManualRadiusClient(RadiusClient):
    """ينفّذ كل العمليات بإضافة سجل في radius_pending_actions."""

    @property
    def mode(self) -> str:
        return "manual"

    # ─── helper داخلي ──────────────────────────────────────────────────
    def _enqueue(
        self,
        action_type: str,
        *,
        target_kind: str = "",
        target_external_id: str = "",
        beneficiary_id: int | None = None,
        payload: dict | None = None,
        requested_by: str = "",
        notes: str = "",
    ) -> Result:
        row = legacy.execute_sql(
            """
            INSERT INTO radius_pending_actions (
                action_type, target_kind, target_external_id,
                beneficiary_id, payload_json,
                requested_by_account_id, requested_by_username, notes,
                attempted_by_mode
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'manual')
            RETURNING id
            """,
            [
                action_type,
                target_kind,
                target_external_id,
                beneficiary_id,
                _json_dumps(payload or {}),
                None,  # account_id يُحدَّد من session في الـ caller
                requested_by or "",
                notes or "",
            ],
            fetchone=True,
        )
        pending_id = (row or {}).get("id") or (row[0] if row and not isinstance(row, dict) else None)
        try:
            from app.services.notification_service import notify_pending_action_created
            notify_pending_action_created(int(pending_id or 0))
        except Exception:
            pass
        return Result.pending(
            action_id=int(pending_id or 0),
            message="تم تسجيل العملية في قائمة الانتظار، سيتم تنفيذها يدويًا من قبل الإدارة.",
        )

    # ═══════════════════════════════════════════════════════════════════
    # 🎫 البطاقات
    # ═══════════════════════════════════════════════════════════════════
    def generate_user_cards(
        self,
        category_code: str,
        count: int = 1,
        *,
        radius_offer_external_id: str = "",
        beneficiary_id: int | None = None,
        requested_by: str = "",
        notes: str = "",
    ) -> Result:
        payload = {"category_code": category_code, "count": int(count)}
        if radius_offer_external_id:
            # نمرّر العرض المربوط كي يعرف من ينفّذ الطلب يدويًا أي عرض RADIUS يستخدم.
            payload["radius_offer_external_id"] = str(radius_offer_external_id)
        return self._enqueue(
            "generate_user_cards",
            target_kind="card",
            target_external_id=str(radius_offer_external_id or ""),
            beneficiary_id=beneficiary_id,
            payload=payload,
            requested_by=requested_by,
            notes=notes,
        )

    def list_offers(self) -> list[dict]:
        """قائمة عروض تجريبية صغيرة كي تعمل واجهة «ربط العروض» بلا اتصال حي.

        في الوضع اليدوي لا يوجد اتصال بـ RADIUS؛ نُرجع عيّنة ثابتة توضّح الشكل
        المتوقّع (external_id/name/duration_label/speed/price/active) فقط لأغراض
        العرض والاختبار — لا تُستخدم لأي توليد فعلي.
        """
        return [
            {"external_id": "demo-30", "name": "عرض نصف ساعة (تجريبي)", "duration_label": "30 دقيقة", "speed": "4M/4M", "price": "", "active": True},
            {"external_id": "demo-60", "name": "عرض ساعة (تجريبي)", "duration_label": "60 دقيقة", "speed": "4M/4M", "price": "", "active": True},
            {"external_id": "demo-120", "name": "عرض ساعتين (تجريبي)", "duration_label": "120 دقيقة", "speed": "6M/6M", "price": "", "active": True},
            {"external_id": "demo-240", "name": "عرض 4 ساعات (تجريبي)", "duration_label": "240 دقيقة", "speed": "8M/8M", "price": "", "active": True},
        ]

    def validate_card(self, username: str, password: str) -> Result:
        # في الوضع manual: نتحقق من جدول manual_access_cards محليًا
        row = legacy.query_one(
            "SELECT id, duration_minutes FROM manual_access_cards WHERE card_username=%s AND card_password=%s LIMIT 1",
            [username, password],
        )
        if row:
            return Result.success("البطاقة صالحة محليًا.", card_id=row["id"], duration_minutes=row["duration_minutes"])
        return Result.failure("لم نجد بطاقة بهذه البيانات في المخزون المحلي.")

    def remove_user_card(self, card_external_id: str, *, requested_by: str = "") -> Result:
        return self._enqueue(
            "remove_user_card",
            target_kind="card",
            target_external_id=card_external_id,
            requested_by=requested_by,
        )

    # ═══════════════════════════════════════════════════════════════════
    # 👤 مشتركو اليوزر
    # ═══════════════════════════════════════════════════════════════════
    def create_user(self, username, password, profile_id, *,
                    beneficiary_id=None, requested_by="", **opts) -> Result:
        return self._enqueue(
            "create_user",
            target_kind="user",
            beneficiary_id=beneficiary_id,
            payload={"username": username, "password": password,
                     "profile_id": profile_id, **opts},
            requested_by=requested_by,
        )

    def update_user(self, user_external_id, *, beneficiary_id=None, requested_by="", **changes) -> Result:
        return self._enqueue(
            "update_user",
            target_kind="user",
            target_external_id=user_external_id,
            beneficiary_id=beneficiary_id,
            payload=changes,
            requested_by=requested_by,
        )

    def reset_password(self, user_external_id, new_password="", *,
                       beneficiary_id=None, requested_by="") -> Result:
        return self._enqueue(
            "reset_password",
            target_kind="user",
            target_external_id=user_external_id,
            beneficiary_id=beneficiary_id,
            payload={"new_password": new_password},
            requested_by=requested_by,
        )

    def add_time(self, user_external_id, *, sel_time, add_time,
                 beneficiary_id=None, requested_by="") -> Result:
        return self._enqueue(
            "add_time",
            target_kind="user",
            target_external_id=user_external_id,
            beneficiary_id=beneficiary_id,
            payload={"sel_time": int(sel_time), "add_time": int(add_time)},
            requested_by=requested_by,
        )

    def add_quota_mb(self, user_external_id, mb, *,
                     beneficiary_id=None, requested_by="") -> Result:
        return self._enqueue(
            "add_quota_mb",
            target_kind="user",
            target_external_id=user_external_id,
            beneficiary_id=beneficiary_id,
            payload={"mb": int(mb)},
            requested_by=requested_by,
        )

    def disconnect(self, user_external_id, *,
                   beneficiary_id=None, requested_by="") -> Result:
        return self._enqueue(
            "disconnect",
            target_kind="user",
            target_external_id=user_external_id,
            beneficiary_id=beneficiary_id,
            requested_by=requested_by,
        )

    def set_mac_lock(self, user_external_id, mac="", *, action="set",
                     beneficiary_id=None, requested_by="") -> Result:
        return self._enqueue(
            "set_mac_lock",
            target_kind="user",
            target_external_id=user_external_id,
            beneficiary_id=beneficiary_id,
            payload={"mac": mac, "action": action},
            requested_by=requested_by,
        )

    # ═══════════════════════════════════════════════════════════════════
    # 📖 قراءات (Phase 1: لا توجد بيانات حية)
    # ═══════════════════════════════════════════════════════════════════
    def get_online_users(self) -> list[Session]:
        return []

    def get_user_bandwidth(self, user_external_id: str) -> UsageSnapshot | None:
        return None

    def get_user_usage(self, user_external_id: str) -> UsageSnapshot | None:
        return None

    def get_profiles(self) -> list[Profile]:
        return []

    # ═══════════════════════════════════════════════════════════════════
    # 📢 إعلانات
    # ═══════════════════════════════════════════════════════════════════
    def broadcast_sms(self, message, *, profile_filter_external_id="", requested_by="") -> Result:
        return self._enqueue(
            "broadcast_sms",
            target_kind="profile" if profile_filter_external_id else "",
            target_external_id=profile_filter_external_id,
            payload={"message": message},
            requested_by=requested_by,
        )

    # ═══════════════════════════════════════════════════════════════════
    # 🗂️ pending actions
    # ═══════════════════════════════════════════════════════════════════
    def list_pending_actions(self, *, action_type="", status="pending", limit=50) -> list[PendingAction]:
        sql = "SELECT * FROM radius_pending_actions WHERE 1=1"
        params: list = []
        if action_type:
            sql += " AND action_type=%s"
            params.append(action_type)
        if status:
            sql += " AND status=%s"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT %s"
        params.append(int(limit))
        rows = legacy.query_all(sql, params)
        return [
            PendingAction(
                id=int(r["id"]),
                action_type=r["action_type"],
                target_kind=r.get("target_kind") or "",
                target_external_id=r.get("target_external_id") or "",
                beneficiary_id=r.get("beneficiary_id"),
                payload=_json_loads(r.get("payload_json")),
                status=r.get("status") or "pending",
                notes=r.get("notes") or "",
                requested_at=r.get("requested_at"),
            )
            for r in rows
        ]

    def _update_pending_status(self, action_id, status, *, executed_by="", error="", notes="", api_response=None):
        legacy.execute_sql(
            """
            UPDATE radius_pending_actions
            SET status=%s,
                executed_by_username=%s,
                error_message=%s,
                notes=CASE WHEN %s <> '' THEN %s ELSE notes END,
                api_response_json=%s,
                executed_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            [
                status,
                executed_by or "",
                error or "",
                notes or "",
                notes or "",
                _json_dumps(api_response or {}),
                int(action_id),
            ],
        )
        try:
            from app.services.notification_service import notify_pending_action_updated
            notify_pending_action_updated(int(action_id), status, notes or error or "")
        except Exception:
            pass

    def mark_pending_done(self, action_id, *, executed_by="", api_response=None, notes="") -> Result:
        self._update_pending_status(
            action_id, "done",
            executed_by=executed_by, api_response=api_response, notes=notes,
        )
        return Result.success("تم وضع علامة منفّذ على العملية.")

    def mark_pending_failed(self, action_id, *, error_message, executed_by="") -> Result:
        self._update_pending_status(
            action_id, "failed",
            executed_by=executed_by, error=error_message,
        )
        return Result.success("تم وضع علامة فشل على العملية.")

    def cancel_pending(self, action_id, *, executed_by="", notes="") -> Result:
        self._update_pending_status(
            action_id, "cancelled",
            executed_by=executed_by, notes=notes,
        )
        return Result.success("تم إلغاء العملية.")
