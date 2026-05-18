"""
card_dispatcher — منسّق إصدار البطاقات.

يجمع بين quota_engine + radius_client + جداول البطاقات الحالية.

الواجهات الرئيسية:
    issue_card_from_inventory(beneficiary_id, category_code, *, actor_username)
        → يصرف بطاقة من المخزون (manual_access_cards) ويسجّل التسليم.

    request_card_via_radius(beneficiary_id, category_code, *, actor_username)
        → يطلب من RadiusClient توليد بطاقة (Phase 1: pending action، Phase 2: API).

    issue_pending_card(action_id, *, card_username, card_password, actor_username)
        → ينفّذ pending action يدويًا — يدخل البطاقة من إدخال المدير.

كل العمليات تكتب في card_audit_log + audit_logs العام.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app import legacy

from .access_rules import (
    is_access_mode_allowed,
    is_card_category_allowed_for_user_type,
    CARDS,
    USER_TYPE_LABELS,
)
from .quota_engine import (
    QuotaDecision,
    check_quota,
    get_category_by_code,
)
from .radius_client import get_radius_client
from .radius_client.base import RadiusClientError, RadiusClientNotImplemented
from .smart_search import smart_search_clause


@dataclass
class DispatchResult:
    ok: bool
    message: str = ""
    card_username: str = ""
    card_password: str = ""
    issued_card_id: int | None = None
    pending_action_id: int | None = None
    duration_minutes: int = 0
    duration_label: str = ""
    quota: QuotaDecision | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def fail(cls, message: str, quota: QuotaDecision | None = None) -> "DispatchResult":
        return cls(ok=False, message=message, quota=quota)


# ─── audit helper ────────────────────────────────────────────────────
def _audit(event_type: str, *, beneficiary_id=None, category_code="",
           issued_card_id=None, actor_account_id=None, actor_username="",
           actor_kind="admin", details=None, pending_action_id=None):
    try:
        legacy.execute_sql(
            """
            INSERT INTO card_audit_log (
                event_type, beneficiary_id, card_category_code, issued_card_id,
                actor_account_id, actor_username, actor_kind, details_json,
                related_pending_action_id
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            [
                event_type,
                beneficiary_id,
                category_code or "",
                issued_card_id,
                actor_account_id,
                actor_username or "",
                actor_kind,
                json.dumps(details or {}, ensure_ascii=False, default=str),
                pending_action_id,
            ],
        )
    except Exception:
        # لا نُفشل العملية الأصلية بسبب audit log
        pass


def _resolve_actor(actor_username: str = "") -> tuple[int | None, str]:
    """من session أو من الـ caller."""
    from flask import session
    account_id = session.get("account_id")
    username = actor_username or session.get("username") or session.get("beneficiary_username") or "system"
    return account_id, username


# ─── المسار 1: إصدار فوري من المخزون اليدوي ──────────────────────────
def issue_card_from_inventory(
    beneficiary_id: int,
    category_code: str,
    *,
    actor_username: str = "",
    skip_quota: bool = False,
) -> DispatchResult:
    """
    المسار اليدوي القديم: يأخذ بطاقة جاهزة من manual_access_cards ويسلّمها.
    يحترم quota_engine إلا إذا skip_quota=True (للإدارة بقرار صريح).
    """
    beneficiary = legacy.query_one(
        "SELECT id, full_name, phone, user_type FROM beneficiaries WHERE id=%s LIMIT 1",
        [beneficiary_id],
    )
    if not beneficiary:
        return DispatchResult.fail("المشترك غير موجود.")

    # فحص قاعدة الوصول حسب نوع المشترك
    user_type = (beneficiary.get("user_type") or "").strip().lower()
    if user_type and not is_access_mode_allowed(user_type, CARDS):
        ut_label = USER_TYPE_LABELS.get(user_type, user_type)
        return DispatchResult.fail(
            f"المشترك ({ut_label}) غير مؤهل لاستخدام نظام البطاقات وفق القواعد."
        )

    # قاعدة فئات البطاقات حسب نوع المشترك (مثل: توجيهي → نصف ساعة فقط)
    if user_type and not is_card_category_allowed_for_user_type(user_type, category_code):
        ut_label = USER_TYPE_LABELS.get(user_type, user_type)
        return DispatchResult.fail(
            f"المشترك ({ut_label}) مسموح له بطاقة نصف ساعة فقط — لا يمكن إصدار {category_code}."
        )

    category = get_category_by_code(category_code)
    if not category:
        return DispatchResult.fail("فئة البطاقة غير معروفة.")

    quota = None
    if not skip_quota:
        quota = check_quota(beneficiary_id, category_code)
        if not quota.allowed:
            _audit(
                "request_rejected_quota",
                beneficiary_id=beneficiary_id,
                category_code=category_code,
                actor_username=actor_username,
                details={"reason": quota.reason, "decision": quota.as_dict()},
            )
            return DispatchResult.fail(quota.reason, quota=quota)

    # سحب من المخزون
    card = legacy.query_one(
        """
        SELECT * FROM manual_access_cards
        WHERE duration_minutes=%s
          AND NOT EXISTS (
              SELECT 1 FROM beneficiary_issued_cards bic
              WHERE bic.card_username = manual_access_cards.card_username
                AND bic.card_password = manual_access_cards.card_password
          )
        ORDER BY id ASC
        LIMIT 1
        """,
        [int(category["duration_minutes"])],
    )
    if not card:
        try:
            from app.services.notification_service import notify_inventory_empty
            notify_inventory_empty(category.get("label_ar") or "", category_code)
        except Exception:
            pass
        return DispatchResult.fail(
            f"لا توجد بطاقات متاحة لفئة {category['label_ar']} في المخزون.",
            quota=quota,
        )

    account_id, username = _resolve_actor(actor_username)

    # سجّل التسليم
    inserted = legacy.execute_sql(
        """
        INSERT INTO beneficiary_issued_cards (
            beneficiary_id, duration_minutes, card_username, card_password,
            issued_by, router_login_url_snapshot
        ) VALUES (%s,%s,%s,%s,%s,%s)
        RETURNING id
        """,
        [
            beneficiary_id,
            int(category["duration_minutes"]),
            card["card_username"],
            card["card_password"],
            username,
            _router_url(),
        ],
        fetchone=True,
    )
    issued_id = int((inserted or {}).get("id") or 0)

    # احذف من المخزون
    legacy.execute_sql("DELETE FROM manual_access_cards WHERE id=%s", [card["id"]])

    _audit(
        "card_issued_from_inventory",
        beneficiary_id=beneficiary_id,
        category_code=category_code,
        issued_card_id=issued_id,
        actor_account_id=account_id,
        actor_username=username,
        details={
            "duration_minutes": int(category["duration_minutes"]),
            "duration_label": category["label_ar"],
            "card_username": card["card_username"],
        },
    )
    try:
        from app.services.notification_service import notify_card_issued
        notify_card_issued(beneficiary_id, issued_id, category.get("label_ar") or "", username)
    except Exception:
        pass

    return DispatchResult(
        ok=True,
        message=f"تم إصدار بطاقة {category['label_ar']} بنجاح.",
        card_username=card["card_username"],
        card_password=card["card_password"],
        issued_card_id=issued_id,
        duration_minutes=int(category["duration_minutes"]),
        duration_label=category["label_ar"],
        quota=quota,
    )


# ─── المسار 2: عبر RadiusClient (Phase 2 سيستخدم API) ────────────────
def request_card_via_radius(
    beneficiary_id: int,
    category_code: str,
    *,
    actor_username: str = "",
    skip_quota: bool = False,
    notes: str = "",
) -> DispatchResult:
    """
    يطلب توليد بطاقة عبر RadiusClient.
    Phase 1: المدير يفتح pending actions ويسلّم البطاقة يدويًا.
    Phase 2: الـ API يولّدها مباشرةً.
    """
    beneficiary = legacy.query_one(
        "SELECT id, full_name, phone, user_type FROM beneficiaries WHERE id=%s LIMIT 1",
        [beneficiary_id],
    )
    if not beneficiary:
        return DispatchResult.fail("المشترك غير موجود.")

    user_type = (beneficiary.get("user_type") or "").strip().lower()
    if user_type and not is_access_mode_allowed(user_type, CARDS):
        ut_label = USER_TYPE_LABELS.get(user_type, user_type)
        return DispatchResult.fail(
            f"المشترك ({ut_label}) غير مؤهل لاستخدام نظام البطاقات."
        )

    # قاعدة فئات البطاقات حسب نوع المشترك (توجيهي → نصف ساعة فقط)
    if user_type and not is_card_category_allowed_for_user_type(user_type, category_code):
        ut_label = USER_TYPE_LABELS.get(user_type, user_type)
        return DispatchResult.fail(
            f"المشترك ({ut_label}) مسموح له بطاقة نصف ساعة فقط — لا يمكن طلب {category_code}."
        )

    category = get_category_by_code(category_code)
    if not category:
        return DispatchResult.fail("فئة البطاقة غير معروفة.")

    quota = None
    if not skip_quota:
        quota = check_quota(beneficiary_id, category_code)
        if not quota.allowed:
            _audit(
                "request_rejected_quota",
                beneficiary_id=beneficiary_id,
                category_code=category_code,
                actor_username=actor_username,
                details={"reason": quota.reason},
            )
            return DispatchResult.fail(quota.reason, quota=quota)

    account_id, username = _resolve_actor(actor_username)

    client = get_radius_client()
    fallback_reason = ""
    try:
        result = client.generate_user_cards(
            category_code=category_code,
            count=1,
            beneficiary_id=beneficiary_id,
            requested_by=username,
            notes=notes,
        )
    except (RadiusClientNotImplemented, RadiusClientError) as exc:
        # القراءة من RADIUS قد تكون مفعلة بينما الكتابة ما زالت مغلقة. في هذه
        # الحالة لا نكسر تجربة المشترك؛ نسجل طلبًا يدويًا لتنفذه الإدارة.
        from .radius_client.manual import ManualRadiusClient

        fallback_reason = str(exc)
        client = ManualRadiusClient()
        result = client.generate_user_cards(
            category_code=category_code,
            count=1,
            beneficiary_id=beneficiary_id,
            requested_by=username,
            notes=(f"{notes} — تم تحويله للتنفيذ اليدوي لأن الكتابة على RADIUS غير مفعلة.").strip(" —"),
        )

    _audit(
        "card_request_queued" if client.mode == "manual" else "card_request_sent",
        beneficiary_id=beneficiary_id,
        category_code=category_code,
        actor_account_id=account_id,
        actor_username=username,
        pending_action_id=result.pending_action_id,
        details={
            "mode": client.mode,
            "result_ok": result.ok,
            "message": result.message,
            "fallback_reason": fallback_reason,
        },
    )

    return DispatchResult(
        ok=result.ok,
        message=result.message,
        pending_action_id=result.pending_action_id,
        duration_minutes=int(category["duration_minutes"]),
        duration_label=category["label_ar"],
        quota=quota,
    )


# ─── المسار 3: تنفيذ pending action يدويًا (الإدارة تكتب username/password) ───
def fulfill_pending_card_action(
    action_id: int,
    *,
    card_username: str,
    card_password: str,
    actor_username: str = "",
    notes: str = "",
) -> DispatchResult:
    """
    المدير يفتح طلبًا معلّقًا من نوع generate_user_cards،
    يدخل username/password للبطاقة (إما من المخزون أو من راوتر يدويًا)،
    والنظام يكمل التسليم.
    """
    action = legacy.query_one(
        "SELECT * FROM radius_pending_actions WHERE id=%s LIMIT 1",
        [int(action_id)],
    )
    if not action:
        return DispatchResult.fail("العملية المعلّقة غير موجودة.")
    if action.get("status") != "pending":
        return DispatchResult.fail(f"العملية بحالة {action.get('status')} ولا يمكن تنفيذها.")
    if action.get("action_type") != "generate_user_cards":
        return DispatchResult.fail("هذه العملية ليست طلب بطاقة.")

    payload = action.get("payload_json")
    try:
        payload = json.loads(payload) if isinstance(payload, str) else (payload or {})
    except (TypeError, ValueError):
        payload = {}

    category_code = payload.get("category_code") or ""
    category = get_category_by_code(category_code)
    if not category:
        return DispatchResult.fail("فئة البطاقة في الطلب غير معروفة.")

    beneficiary_id = action.get("beneficiary_id")
    if not beneficiary_id:
        return DispatchResult.fail("الطلب لا يحوي مشتركًا محددًا.")

    if not card_username or not card_password:
        return DispatchResult.fail("اسم المستخدم وكلمة المرور للبطاقة مطلوبان.")

    account_id, username = _resolve_actor(actor_username)

    inserted = legacy.execute_sql(
        """
        INSERT INTO beneficiary_issued_cards (
            beneficiary_id, duration_minutes, card_username, card_password,
            issued_by, router_login_url_snapshot
        ) VALUES (%s,%s,%s,%s,%s,%s)
        RETURNING id
        """,
        [
            beneficiary_id,
            int(category["duration_minutes"]),
            card_username.strip(),
            card_password.strip(),
            username,
            _router_url(),
        ],
        fetchone=True,
    )
    issued_id = int((inserted or {}).get("id") or 0)

    client = get_radius_client()
    client.mark_pending_done(
        int(action_id),
        executed_by=username,
        api_response={"card_username": card_username, "card_password": card_password, "issued_card_id": issued_id},
        notes=notes,
    )

    _audit(
        "card_issued_manual",
        beneficiary_id=beneficiary_id,
        category_code=category_code,
        issued_card_id=issued_id,
        actor_account_id=account_id,
        actor_username=username,
        pending_action_id=int(action_id),
        details={"card_username": card_username, "notes": notes},
    )
    try:
        from app.services.notification_service import notify_card_issued
        notify_card_issued(int(beneficiary_id), issued_id, category.get("label_ar") or "", username)
    except Exception:
        pass

    return DispatchResult(
        ok=True,
        message=f"تم تسليم بطاقة {category['label_ar']} للمشترك.",
        card_username=card_username,
        card_password=card_password,
        issued_card_id=issued_id,
        pending_action_id=int(action_id),
        duration_minutes=int(category["duration_minutes"]),
        duration_label=category["label_ar"],
    )


# ─── inventory helpers ───────────────────────────────────────────────
def get_inventory_counts() -> list[dict]:
    """عدد البطاقات المتاحة في المخزون لكل فئة."""
    rows = legacy.query_all(
        """
        SELECT
            cc.code,
            cc.label_ar,
            cc.duration_minutes,
            cc.icon,
            cc.color_class,
            cc.is_active,
            COALESCE((
                SELECT COUNT(*) FROM manual_access_cards
                WHERE duration_minutes = cc.duration_minutes
            ), 0) AS available
        FROM card_categories cc
        WHERE cc.is_active=TRUE
          AND cc.code IN ('half_hour','one_hour','two_hours','three_hours','four_hours')
        ORDER BY cc.display_order ASC, cc.duration_minutes ASC
        """
    )
    return rows


def list_recent_audit(limit: int = 100, *, beneficiary_id: int | None = None) -> list[dict]:
    """آخر أحداث تدقيق البطاقات."""
    sql = "SELECT * FROM card_audit_log WHERE 1=1"
    params: list = []
    if beneficiary_id:
        sql += " AND beneficiary_id=%s"
        params.append(int(beneficiary_id))
    sql += " ORDER BY id DESC LIMIT %s"
    params.append(int(limit))
    return legacy.query_all(sql, params)


def list_deliveries(
    limit: int = 100,
    *,
    beneficiary_id: int | None = None,
    category_code: str | None = None,
    q: str | None = None,
    phone: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """سجل تسليم البطاقات مع فلاتر مرنة (id، اسم، جوال، فئة، تاريخ من/إلى)."""
    sql = """
        SELECT bic.*, b.full_name, b.phone
        FROM beneficiary_issued_cards bic
        LEFT JOIN beneficiaries b ON b.id = bic.beneficiary_id
        WHERE 1=1
    """
    params: list = []
    if beneficiary_id:
        sql += " AND bic.beneficiary_id=%s"
        params.append(int(beneficiary_id))
    if category_code:
        category = get_category_by_code(category_code)
        if category:
            sql += " AND bic.duration_minutes=%s"
            params.append(int(category["duration_minutes"]))
    if q:
        # بحث بالاسم أو اسم/كلمة مرور البطاقة أو رقم التسليم (#xxx)
        clause, clause_params = smart_search_clause(
            q,
            text_columns=("b.search_name", "b.full_name", "bic.card_username", "bic.card_password"),
            phone_columns=("b.phone",),
            extra_columns=("bic.issued_by",),
        )
        q_digits = str(q).strip()
        if clause and q_digits.isdigit():
            sql += f" AND ({clause} OR bic.id=%s OR bic.beneficiary_id=%s)"
            params.extend([*clause_params, int(q_digits), int(q_digits)])
        elif clause:
            sql += " AND " + clause
            params.extend(clause_params)
        elif q_digits.isdigit():
            sql += " AND (bic.id=%s OR bic.beneficiary_id=%s)"
            params.extend([int(q_digits), int(q_digits)])
    if phone:
        clause, clause_params = smart_search_clause(phone, phone_columns=("b.phone",))
        if clause:
            sql += " AND " + clause
            params.extend(clause_params)
    if date_from:
        sql += " AND bic.issued_at >= %s"
        params.append(date_from)
    if date_to:
        # حتى نهاية اليوم (24:00 من اليوم المحدد)
        sql += " AND bic.issued_at < DATE(%s, '+1 day')" if legacy.is_sqlite_database_url() else " AND bic.issued_at < (DATE(%s) + INTERVAL '1 day')"
        params.append(date_to)
    sql += " ORDER BY bic.id DESC LIMIT %s"
    params.append(int(limit))
    return legacy.query_all(sql, params)


def _router_url() -> str:
    """قراءة آمنة لرابط دخول الراوتر (يستخدم helper الموجود)."""
    try:
        return legacy.get_router_login_url()
    except Exception:
        return ""
