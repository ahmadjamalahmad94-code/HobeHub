"""
RadiusClient ABC — واجهة موحدة لكل التفاعلات مع RADIUS.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .dtos import PendingAction, Profile, Result, Session, UsageSnapshot


class RadiusClientError(Exception):
    """خطأ عام من RadiusClient."""


class RadiusClientNotImplemented(RadiusClientError):
    """العملية مكتوبة لكنها لم تُربط بـ API الحقيقي."""


class RadiusClient(ABC):
    """الواجهة الموحدة."""

    @property
    @abstractmethod
    def mode(self) -> str: ...

    @property
    def under_development(self) -> bool:
        return self.mode != "live"

    # ── Cards ─────────────────────────────────────────────
    @abstractmethod
    def generate_user_cards(self, category_code: str, count: int = 1, *, radius_offer_external_id: str = "", beneficiary_id: int | None = None, requested_by: str = "", notes: str = "") -> Result: ...

    def list_offers(self) -> list[dict]:
        """يسرد عروض/باقات RADIUS القابلة للربط (marketplace offers).

        كل عنصر: {external_id, name, duration_label, speed, price, active}.
        الافتراضي (الوضع اليدوي/غير الحي) يُرجع قائمة فارغة — تتجاوزه النسختان
        Manual (stub) و Live (حي). قابلة للتجاوز كي لا تُكسر أي subclass قائمة.
        """
        return []

    @abstractmethod
    def validate_card(self, username: str, password: str) -> Result: ...

    @abstractmethod
    def remove_user_card(self, card_external_id: str, *, requested_by: str = "") -> Result: ...

    # ── Username users ────────────────────────────────────
    @abstractmethod
    def create_user(self, username: str, password: str, profile_id: str, *, beneficiary_id: int | None = None, requested_by: str = "", **opts: Any) -> Result: ...

    @abstractmethod
    def update_user(self, user_external_id: str, *, beneficiary_id: int | None = None, requested_by: str = "", **changes: Any) -> Result: ...

    @abstractmethod
    def reset_password(self, user_external_id: str, new_password: str = "", *, beneficiary_id: int | None = None, requested_by: str = "") -> Result: ...

    @abstractmethod
    def add_time(self, user_external_id: str, *, sel_time: int, add_time: int, beneficiary_id: int | None = None, requested_by: str = "") -> Result: ...

    @abstractmethod
    def add_quota_mb(self, user_external_id: str, mb: int, *, beneficiary_id: int | None = None, requested_by: str = "") -> Result: ...

    @abstractmethod
    def disconnect(self, user_external_id: str, *, beneficiary_id: int | None = None, requested_by: str = "") -> Result: ...

    @abstractmethod
    def set_mac_lock(self, user_external_id: str, mac: str = "", *, action: str = "set", beneficiary_id: int | None = None, requested_by: str = "") -> Result: ...

    # ── Reads ──────────────────────────────────────────────
    @abstractmethod
    def get_online_users(self) -> list[Session]: ...

    @abstractmethod
    def get_user_bandwidth(self, user_external_id: str) -> UsageSnapshot | None: ...

    @abstractmethod
    def get_user_usage(self, user_external_id: str) -> UsageSnapshot | None: ...

    @abstractmethod
    def get_profiles(self) -> list[Profile]: ...

    # ── Broadcast ─────────────────────────────────────────
    @abstractmethod
    def broadcast_sms(self, message: str, *, profile_filter_external_id: str = "", requested_by: str = "") -> Result: ...

    # ── Health / Info (default impl: not available in manual mode) ─
    def health_check(self) -> dict:
        return {"ok": False, "mode": self.mode, "message": "manual mode — no live connection"}

    def get_my_permissions(self) -> dict:
        return {"ok": False, "mode": self.mode, "message": "غير متاح في الوضع اليدوي"}

    def get_my_balance(self) -> dict:
        return {"ok": False, "mode": self.mode, "message": "غير متاح في الوضع اليدوي"}

    def get_server_status(self) -> dict:
        return {"ok": False, "mode": self.mode, "message": "غير متاح في الوضع اليدوي"}

    # ── Pending actions ──────────────────────────────────
    @abstractmethod
    def list_pending_actions(self, *, action_type: str = "", status: str = "pending", limit: int = 50) -> list[PendingAction]: ...

    @abstractmethod
    def mark_pending_done(self, action_id: int, *, executed_by: str = "", api_response: dict | None = None, notes: str = "") -> Result: ...

    @abstractmethod
    def mark_pending_failed(self, action_id: int, *, error_message: str, executed_by: str = "") -> Result: ...

    @abstractmethod
    def cancel_pending(self, action_id: int, *, executed_by: str = "", notes: str = "") -> Result: ...
