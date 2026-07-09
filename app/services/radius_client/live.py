"""
LiveRadiusClient — Phase 2 (تفعيل تدريجي).

✅ مُفعَّل الآن (قراءة فقط):
    - health_check  → GET /get_app_version (بدون auth)
    - get_my_permissions
    - get_my_balance
    - get_server_status

🚧 لا يزال معطّلًا (Write operations):
    - generate_user_cards, create_user, reset_password, update_user
    - add_time, add_quota_mb, disconnect, set_mac_lock, broadcast_sms

ملاحظات الاتصال:
    - Base URL: /app_ad2/ (وليس /app_ad/)
    - Password MD5-hashed
    - Headers: X-Api-Key + adv_auth_ad
    - Login response: account.api_key

التفعيل:
    .env:
        RADIUS_API_BASE_URL=http://HOST/app_ad2
        RADIUS_API_MASTER_KEY=<license_id>
        RADIUS_API_USERNAME=<sub_admin>
        RADIUS_API_PASSWORD=<plain>
        RADIUS_MODE=live
        RADIUS_API_READY=1
"""
from __future__ import annotations

import hashlib
import os

from .base import RadiusClient, RadiusClientError, RadiusClientNotImplemented
from .dtos import Result
from ..radius_config import resolve_radius_connection


# ─── helpers ──────────────────────────────────────────────────────────
def _api_ready() -> bool:
    return bool(resolve_radius_connection().read_enabled)


def _writes_enabled() -> bool:
    """write ops محمية بـ flag منفصل — تتطلب تفعيلًا صريحًا إضافيًا."""
    return bool(resolve_radius_connection().write_enabled)


def _guard_read():
    if not _api_ready():
        raise RadiusClientNotImplemented(
            "🚧 RADIUS API غير مفعّل. اضبط RADIUS_API_READY=1."
        )


def _guard_write():
    if not _api_ready():
        raise RadiusClientNotImplemented("🚧 RADIUS API غير مفعّل.")
    if not _writes_enabled():
        raise RadiusClientNotImplemented(
            "🚧 عمليات الكتابة في الـ API ما زالت قيد التطوير. "
            "اضبط RADIUS_API_WRITES_ENABLED=1 بعد اختبار كامل."
        )


def md5_password(plain: str) -> str:
    """يحوّل الباسوورد إلى MD5 hash كما يتوقع الـ API."""
    return hashlib.md5((plain or "").encode("utf-8")).hexdigest()


def _int_or_zero(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _normalize_card(raw: dict) -> dict:
    """يوحّد شكل بطاقة مُولّدة قادمة من رد RADIUS (دفاعي مع تعدد أسماء الحقول)."""
    def pick(*keys: str) -> str:
        for k in keys:
            v = raw.get(k)
            if v not in (None, ""):
                return str(v).strip()
        return ""

    return {
        "username": pick("card_username", "username", "user_name", "login", "card_no", "card_number", "user"),
        "password": pick("card_password", "password", "pass", "pin", "code", "secret"),
        "external_id": pick("external_id", "id", "card_id", "user_id", "uid"),
        "duration_minutes": _int_or_zero(
            raw.get("duration_minutes") or raw.get("duration") or raw.get("minutes")
        ),
    }


def _extract_first_card(body: dict) -> dict | None:
    """يستخرج أول بطاقة صالحة (username+password) من رد RADIUS مهما كان شكله."""
    candidates: list = []
    for key in ("cards", "data", "results", "generated", "__list__"):
        val = body.get(key)
        if isinstance(val, list):
            candidates = val
            break
        if isinstance(val, dict):
            candidates = [val]
            break
    if not candidates and (
        body.get("username") or body.get("card_username") or body.get("card_no")
    ):
        candidates = [body]
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        card = _normalize_card(raw)
        if card["username"] and card["password"]:
            return card
    return None


def _as_bool(value) -> bool:
    token = str(value).strip().lower()
    return token in ("1", "true", "yes", "on", "active", "enabled", "t")


def _offer_pick(raw: dict, *keys: str) -> str:
    for k in keys:
        v = raw.get(k)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _offer_duration_label(raw: dict) -> str:
    label = _offer_pick(raw, "duration_label", "duration_text", "validity_label", "validity")
    if label:
        return label
    mins = _int_or_zero(raw.get("duration_minutes") or raw.get("minutes") or raw.get("duration"))
    if mins:
        return f"{mins} دقيقة"
    return ""


def _offer_speed(raw: dict) -> str:
    speed = _offer_pick(
        raw, "speed", "rate_limit", "mikrotik_rate_limit", "Mikrotik-Rate-Limit",
        "bandwidth", "rate", "speed_label",
    )
    if speed:
        return speed
    up = _offer_pick(raw, "speed_up", "up", "upload")
    down = _offer_pick(raw, "speed_down", "down", "download")
    if up or down:
        return f"{down or '?'}/{up or '?'}"
    return ""


def _offer_active(raw: dict) -> bool:
    for k in ("active", "is_active", "enabled"):
        if k in raw and raw.get(k) is not None:
            return _as_bool(raw.get(k))
    status = str(raw.get("status") or "").strip().lower()
    if status in ("disabled", "inactive", "0", "false", "off", "expired"):
        return False
    return True  # افتراضيًا مرئي ما لم يُصرَّح بخلافه


def _normalize_offer(raw: dict) -> dict | None:
    """يوحّد عرض/باقة RADIUS إلى شكل نظيف. يُرجع None إن غاب external_id."""
    if not isinstance(raw, dict):
        return None
    external_id = _offer_pick(
        raw, "external_id", "offer_id", "profile_id", "batch_id",
        "id", "card_id", "uid", "pid",
    )
    if not external_id:
        return None
    name = _offer_pick(
        raw, "name", "offer_name", "title", "profile_name", "label",
        "batch_name", "description",
    ) or external_id
    return {
        "external_id": external_id,
        "name": name,
        "duration_label": _offer_duration_label(raw),
        "speed": _offer_speed(raw),
        "price": _offer_pick(raw, "price", "cost", "amount", "sell_price", "wholesale_price", "wholesale"),
        "active": _offer_active(raw),
    }


def _extract_offers(body: dict) -> list[dict]:
    """يستخرج قائمة العروض من رد RADIUS مهما كان مفتاح القائمة."""
    candidates: list = []
    for key in ("offers", "batches", "card_batches", "profiles", "data", "results", "__list__"):
        val = body.get(key)
        if isinstance(val, list):
            candidates = val
            break
        if isinstance(val, dict):
            candidates = list(val.values())
            break
    offers: list[dict] = []
    for raw in candidates:
        offer = _normalize_offer(raw)
        if offer:
            offers.append(offer)
    return offers


_REQUEST_TIMEOUT = 15


class LiveRadiusClient(RadiusClient):
    """Phase 2 — قراءة فقط مُفعَّلة، كتابة معطّلة افتراضيًا."""

    def __init__(self):
        # الاتصال يُحلَّل من قاعدة البيانات (مصدر الحقيقة) مع احتياطي env.
        cfg = resolve_radius_connection()
        self.base_url = (cfg.base_url or "").rstrip("/")
        self.master_key = cfg.master_key
        self.api_username = cfg.service_username
        self.api_password = cfg.service_password
        self._api_key: str | None = None
        self._login_failure: str | None = None
        self._login_failure_until: float = 0.0
        self._verify_ssl = cfg.verify_ssl

    @property
    def mode(self) -> str:
        return "live"

    # ─── HTTP layer ──────────────────────────────────────────────────
    def _endpoint_url(self, endpoint: str) -> str:
        if not self.base_url:
            raise RadiusClientError("RADIUS_API_BASE_URL غير محدد.")
        return f"{self.base_url}/{endpoint.lstrip('/')}"

    def _headers(self, *, with_auth: bool = True) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.master_key:
            h["X-Api-Key"] = self.master_key
        if with_auth and self._api_key:
            h["adv_auth_ad"] = self._api_key
        return h

    def _http_post(self, endpoint: str, data: dict | None = None, *, with_auth: bool = True) -> dict:
        """POST عام مع معالجة أخطاء. يرجع dict دائمًا."""
        try:
            import requests
        except ImportError:
            raise RadiusClientError("مكتبة requests غير مثبتة — pip install requests")

        url = self._endpoint_url(endpoint)
        try:
            r = requests.post(
                url,
                data=data or {},
                headers=self._headers(with_auth=with_auth),
                timeout=_REQUEST_TIMEOUT,
                verify=self._verify_ssl,
            )
        except Exception as exc:
            return {"error": True, "__transport_error__": str(exc), "__url__": url}

        out: dict = {"__http_status__": r.status_code, "__url__": url}
        try:
            body = r.json()
            if isinstance(body, dict):
                out.update(body)
            else:
                out["__list__"] = body
        except ValueError:
            out["__raw__"] = r.text[:500]
            out["error"] = True
            out["msg"] = "الرد ليس JSON صحيحًا"
        return out

    def _login(self) -> str:
        """يطلب /login إن لم يكن لديه api_key محفوظ. يكاش فشل الـ login لـ 60ث منعًا للحظر."""
        import time
        if self._api_key:
            return self._api_key
        # حماية: لو login فشل قبل قليل، لا تحاول مجددًا
        if self._login_failure and time.time() < self._login_failure_until:
            remaining = int(self._login_failure_until - time.time())
            raise RadiusClientError(
                f"Login مُعطَّل مؤقتًا (تبقّى {remaining}ث) — تجنبًا للحظر. "
                f"السبب: {self._login_failure}"
            )
        if not self.api_username or not self.api_password:
            raise RadiusClientError("بيانات اعتماد API ناقصة (USERNAME أو PASSWORD).")
        body = self._http_post(
            "login",
            {
                "username": self.api_username,
                "password": md5_password(self.api_password),
            },
            with_auth=False,
        )
        if body.get("error"):
            err = body.get("message") or body.get("msg") or body.get("__transport_error__") or str(body)
            # احفظ الفشل لـ 60ث
            self._login_failure = str(err)[:200]
            self._login_failure_until = time.time() + 60
            raise RadiusClientError(f"Login failed: {err}")
        api_key = (body.get("account") or {}).get("api_key")
        if not api_key:
            self._login_failure = "Login نجح بدون api_key"
            self._login_failure_until = time.time() + 60
            raise RadiusClientError(self._login_failure)
        # نجاح — امسح الفشل
        self._api_key = api_key
        self._login_failure = None
        self._login_failure_until = 0
        return api_key

    # ═══════════════════════════════════════════════════════════════════
    # ✅ Read operations (مُفعَّلة)
    # ═══════════════════════════════════════════════════════════════════
    def ping(self) -> dict:
        """اختبار اتصال آمن (بدون auth) بصرف النظر عن read_enabled — يخدم زر
        «اختبار الاتصال» في صفحة الإعدادات كي يتحقق المسؤول من الهدف قبل تفعيل
        القراءة. عملية قراءة فقط (get_app_version) لا تسبب أي حظر."""
        if not self.base_url:
            return {"ok": False, "mode": "live", "error": "Base URL غير محدد."}
        body = self._http_post("get_app_version", {}, with_auth=False)
        if body.get("error"):
            return {
                "ok": False,
                "mode": "live",
                "error": body.get("msg") or body.get("__transport_error__") or "تعذّر الاتصال",
                "http_status": body.get("__http_status__"),
                "url": body.get("__url__"),
            }
        return {"ok": True, "mode": "live", "data": {k: v for k, v in body.items() if not k.startswith("__")}}

    def health_check(self) -> dict:
        """ping بسيط بدون auth — يرجع معلومات نسخة الـ API."""
        if not _api_ready():
            return {"ok": False, "mode": "live", "message": "RADIUS_API_READY=0"}
        body = self._http_post("get_app_version", {}, with_auth=False)
        if body.get("error"):
            return {
                "ok": False,
                "mode": "live",
                "error": body.get("msg") or body.get("__transport_error__") or "خطأ غير محدد",
                "http_status": body.get("__http_status__"),
                "url": body.get("__url__"),
            }
        return {"ok": True, "mode": "live", "data": {k: v for k, v in body.items() if not k.startswith("__")}}

    def get_my_permissions(self) -> dict:
        try:
            _guard_read()
            self._login()
            body = self._http_post("get_my_permissions", {})
            if body.get("error"):
                return {"ok": False, "error": body.get("msg") or body.get("__transport_error__")}
            return {"ok": True, "data": {k: v for k, v in body.items() if not k.startswith("__")}}
        except (RadiusClientError, RadiusClientNotImplemented) as exc:
            return {"ok": False, "error": str(exc)}

    def get_my_balance(self) -> dict:
        try:
            _guard_read()
            self._login()
            body = self._http_post("get_my_balance", {})
            if body.get("error"):
                return {"ok": False, "error": body.get("msg") or body.get("__transport_error__")}
            return {"ok": True, "data": {k: v for k, v in body.items() if not k.startswith("__")}}
        except (RadiusClientError, RadiusClientNotImplemented) as exc:
            return {"ok": False, "error": str(exc)}

    def get_server_status(self) -> dict:
        try:
            _guard_read()
            self._login()
            body = self._http_post("get_server_status", {})
            if body.get("error"):
                return {"ok": False, "error": body.get("msg") or body.get("__transport_error__")}
            return {"ok": True, "data": {k: v for k, v in body.items() if not k.startswith("__")}}
        except (RadiusClientError, RadiusClientNotImplemented) as exc:
            return {"ok": False, "error": str(exc)}

    # ═══════════════════════════════════════════════════════════════════
    # 🚧 Write operations (معطّلة)
    # ═══════════════════════════════════════════════════════════════════
    def generate_user_cards(self, category_code, count=1, *, radius_offer_external_id="", beneficiary_id=None, requested_by="", notes=""):
        """يولّد بطاقة/بطاقات فوريًا من عرض RADIUS ويُرجع بياناتها.

        محميّة بـ RADIUS_API_WRITES_ENABLED (تبقى «قيد التطوير» حتى تُفعَّل الكتابة
        وتُختبر). عند النجاح تُرجع Result.success يحوي بيانات البطاقة في .data
        (card_username / card_password / external_id) ليقوم card_dispatcher
        بحفظها وتسليمها للمشترك. عند فشل الاتصال/الرد تُرجع Result.failure دون
        تلفيق أي بطاقة.
        """
        _guard_write()
        self._login()
        endpoint = (os.getenv("RADIUS_API_CARDS_ENDPOINT", "") or "generate_user_cards").strip().lstrip("/")
        offer_id = str(radius_offer_external_id or "").strip()
        params = {
            "category_code": category_code,
            "category": category_code,
            "count": int(count or 1),
            "beneficiary_id": "" if beneficiary_id is None else beneficiary_id,
            "requested_by": requested_by or "",
            "notes": notes or "",
        }
        # العرض المربوط: نمرّره تحت عدة مفاتيح شائعة كي تُولَّد البطاقة *داخل*
        # العرض المحدّد على RADIUS بغض النظر عن اسم الحقل المتوقَّع في الـ API.
        if offer_id:
            params["offer_id"] = offer_id
            params["profile_id"] = offer_id
            params["external_id"] = offer_id
            params["id"] = offer_id
        body = self._http_post(endpoint, params)
        if body.get("error"):
            return Result.failure(
                body.get("message")
                or body.get("msg")
                or body.get("__transport_error__")
                or "تعذّر توليد البطاقة من RADIUS."
            )
        card = _extract_first_card(body)
        if not card:
            return Result.failure("رد RADIUS لا يحتوي على بيانات بطاقة صالحة.")
        return Result.success(
            "تم توليد البطاقة من RADIUS.",
            card_username=card["username"],
            card_password=card["password"],
            external_id=card["external_id"],
            category_code=category_code,
            duration_minutes=card["duration_minutes"],
            api_endpoint=endpoint,
        )

    def validate_card(self, username, password):
        _guard_write()
        raise RadiusClientNotImplemented("validate_card — لم يُختبر بعد")

    def remove_user_card(self, card_external_id, *, requested_by=""):
        _guard_write()
        raise RadiusClientNotImplemented("remove_user_card — لم يُختبر بعد")

    def create_user(self, username, password, profile_id, *, beneficiary_id=None, requested_by="", **opts):
        _guard_write()
        raise RadiusClientNotImplemented("create_user — لم يُختبر بعد")

    def update_user(self, user_external_id, *, beneficiary_id=None, requested_by="", **changes):
        _guard_write()
        raise RadiusClientNotImplemented("update_user — لم يُختبر بعد")

    def reset_password(self, user_external_id, new_password="", *, beneficiary_id=None, requested_by=""):
        _guard_write()
        raise RadiusClientNotImplemented("reset_password — لم يُختبر بعد")

    def add_time(self, user_external_id, *, sel_time, add_time, beneficiary_id=None, requested_by=""):
        _guard_write()
        raise RadiusClientNotImplemented("add_time — لم يُختبر بعد")

    def add_quota_mb(self, user_external_id, mb, *, beneficiary_id=None, requested_by=""):
        _guard_write()
        raise RadiusClientNotImplemented("add_quota_mb — لم يُختبر بعد")

    def disconnect(self, user_external_id, *, beneficiary_id=None, requested_by=""):
        _guard_write()
        raise RadiusClientNotImplemented("disconnect — لم يُختبر بعد")

    def set_mac_lock(self, user_external_id, mac="", *, action="set", beneficiary_id=None, requested_by=""):
        _guard_write()
        raise RadiusClientNotImplemented("set_mac_lock — لم يُختبر بعد")

    def get_online_users(self) -> list:
        """قائمة الجلسات المتصلة حاليًا. ✅ مُفعَّل."""
        try:
            _guard_read()
            self._login()
            body = self._http_post("get_online_users", {})
            if body.get("error"):
                return []
            data = body.get("data") or body.get("__list__") or []
            return data if isinstance(data, list) else []
        except (RadiusClientError, RadiusClientNotImplemented):
            return []

    def get_user_bandwidth(self, user_external_id):
        """استخدام لحظي للمشترك. ✅ مُفعَّل."""
        try:
            _guard_read()
            self._login()
            body = self._http_post("get_user_bandwidth", {"user_id": user_external_id})
            if body.get("error"):
                return None
            return body  # raw dict — caller يقرر
        except (RadiusClientError, RadiusClientNotImplemented):
            return None

    def get_user_usage(self, user_external_id):
        """ملخص استخدام تاريخي. ✅ مُفعَّل."""
        try:
            _guard_read()
            self._login()
            body = self._http_post("get_user_usage", {"user_id": user_external_id})
            if body.get("error"):
                return None
            return body
        except (RadiusClientError, RadiusClientNotImplemented):
            return None

    def get_user_sessions(self, user_external_id):
        """جلسات المستخدم السابقة/الحالية. قراءة فقط وتستخدمها طبقة حالة البطاقات."""
        try:
            _guard_read()
            self._login()
            body = self._http_post(
                "get_user_sessions",
                {"user_id": user_external_id, "username": user_external_id},
            )
            if body.get("error"):
                return None
            return body
        except (RadiusClientError, RadiusClientNotImplemented):
            return None

    def get_profiles(self) -> list:
        """قائمة الباقات المتاحة. ✅ مُفعَّل."""
        try:
            _guard_read()
            self._login()
            body = self._http_post("get_profiles_for_user", {})
            if body.get("error"):
                return []
            data = body.get("data") or body.get("profiles") or body.get("__list__") or []
            return data if isinstance(data, list) else []
        except (RadiusClientError, RadiusClientNotImplemented):
            return []

    def list_offers(self) -> list:
        """قائمة عروض/باقات RADIUS القابلة للربط (marketplace offers). ✅ مُفعَّل (قراءة).

        يستدعي نقطة النهاية التي تسرد الباقات/العروض المتاحة لحساب الخدمة. لا يوجد
        في سطح app_ad2 الموثّق نقطة «سرد عروض بطاقات» مستقلة؛ الأقرب المؤكَّد هو
        ``get_profiles_for_user`` (نفسها التي يستخدمها get_profiles) والتي تُرجع
        الباقات/العروض التي يولّد المسؤول البطاقات ضمنها. الاسم قابل للتبديل عبر
        ``RADIUS_API_OFFERS_ENDPOINT`` دون إعادة نشر إن كشف الـ marketplace نقطة
        عروض مخصّصة — بلا أي تعديل على RADIUS.
        """
        try:
            _guard_read()
            self._login()
            endpoint = (os.getenv("RADIUS_API_OFFERS_ENDPOINT", "") or "get_profiles_for_user").strip().lstrip("/")
            body = self._http_post(endpoint, {})
            if body.get("error"):
                return []
            return _extract_offers(body)
        except (RadiusClientError, RadiusClientNotImplemented):
            return []

    def broadcast_sms(self, message, *, profile_filter_external_id="", requested_by=""):
        _guard_write()
        raise RadiusClientNotImplemented("broadcast_sms — لم يُختبر بعد")


    # ─── إضافات (✅ مُفعَّلة) ─────────────────────────────────
    def quick_stats(self) -> dict:
        """KPIs لحظية للوحة الإدارة."""
        try:
            _guard_read()
            self._login()
            body = self._http_post("quick_stats", {})
            if body.get("error"):
                return {"ok": False, "error": body.get("message") or body.get("msg")}
            return {"ok": True, "data": {k: v for k, v in body.items() if not k.startswith("__")}}
        except (RadiusClientError, RadiusClientNotImplemented) as exc:
            return {"ok": False, "error": str(exc)}

    def search_users(self, query: str = "", limit: int = 50) -> dict:
        """يبحث عن مشتركين باسم/جوال/MAC."""
        try:
            _guard_read()
            self._login()
            body = self._http_post("search_users", {"q": query, "limit": int(limit)})
            if body.get("error"):
                return {"ok": False, "error": body.get("message") or body.get("msg"), "data": []}
            data = body.get("data") or body.get("users") or body.get("__list__") or []
            return {"ok": True, "data": data if isinstance(data, list) else []}
        except (RadiusClientError, RadiusClientNotImplemented) as exc:
            return {"ok": False, "error": str(exc), "data": []}

    def get_dashboard_metrics(self) -> dict:
        """مقاييس داشبورد كاملة."""
        try:
            _guard_read()
            self._login()
            body = self._http_post("get_dashboard_metrics", {})
            if body.get("error"):
                return {"ok": False, "error": body.get("message") or body.get("msg")}
            return {"ok": True, "data": {k: v for k, v in body.items() if not k.startswith("__")}}
        except (RadiusClientError, RadiusClientNotImplemented) as exc:
            return {"ok": False, "error": str(exc)}

    # ─── pending actions (مشتركة مع manual) ─────────────────────────
    def list_pending_actions(self, *, action_type="", status="pending", limit=50):
        from .manual import ManualRadiusClient
        return ManualRadiusClient().list_pending_actions(action_type=action_type, status=status, limit=limit)

    def mark_pending_done(self, action_id, *, executed_by="", api_response=None, notes=""):
        from .manual import ManualRadiusClient
        return ManualRadiusClient().mark_pending_done(action_id, executed_by=executed_by, api_response=api_response, notes=notes)

    def mark_pending_failed(self, action_id, *, error_message, executed_by=""):
        from .manual import ManualRadiusClient
        return ManualRadiusClient().mark_pending_failed(action_id, error_message=error_message, executed_by=executed_by)

    def cancel_pending(self, action_id, *, executed_by="", notes=""):
        from .manual import ManualRadiusClient
        return ManualRadiusClient().cancel_pending(action_id, executed_by=executed_by, notes=notes)
