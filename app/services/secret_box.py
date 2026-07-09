"""
secret_box — تشفير/فك تشفير عكسي خفيف للأسرار المخزَّنة في قاعدة البيانات.

الهدف: عدم تخزين أسرار الـ API (master key / كلمة مرور الخدمة) كنص صريح في
``radius_api_settings``. نستخدم keystream مشتقًّا من ``FLASK_SECRET_KEY`` عبر
HMAC-SHA256 (بدون أي اعتماد خارجي جديد — لا cryptography).

الصيغة المخزَّنة:  ``enc$<base64(nonce(16) + ciphertext)>``

- ``encrypt_secret``: يعيد نصًّا مُشفَّرًا بادئته ``enc$``.
- ``decrypt_secret``: يفك ``enc$...`` ويعيد أي قيمة أخرى كما هي (تمريرة للنص
  الصريح/القديم القادم من متغيرات البيئة).

ملاحظة أمنية: هذا تشويش عكسي مربوط بمفتاح التطبيق، لا بديل عن HSM. الغرض منع
تسرّب النص الصريح من قاعدة البيانات/النسخ الاحتياطية، لا مقاومة مهاجم يملك
``FLASK_SECRET_KEY``. الأسرار لا تُطبع أبدًا في الصفحات أو السجلات.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

_PREFIX = "enc$"
# fallback ثابت للتطوير/الاختبار عندما لا يُضبط FLASK_SECRET_KEY (التطبيق نفسه
# يستخدم مفتاحًا مشابهًا في وضع الـ demo المحلي).
_DEV_FALLBACK = b"hobehub-local-demo-secret-key-do-not-use-in-prod"


def _key() -> bytes:
    secret = (os.getenv("FLASK_SECRET_KEY", "") or "").strip().encode("utf-8")
    if not secret:
        secret = _DEV_FALLBACK
    return hashlib.sha256(secret).digest()


def _keystream(nonce: bytes, length: int) -> bytes:
    key = _key()
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def is_encrypted(value: str | None) -> bool:
    return bool(value) and str(value).startswith(_PREFIX)


def encrypt_secret(plain: str | None) -> str:
    """يُشفّر سرًّا. النص الفارغ يبقى فارغًا (لا نخزّن سرًّا فارغًا)."""
    if plain is None:
        return ""
    plain = str(plain)
    if plain == "":
        return ""
    if is_encrypted(plain):
        # مُشفَّر مسبقًا — لا تُعِد تشفيره
        return plain
    data = plain.encode("utf-8")
    nonce = os.urandom(16)
    stream = _keystream(nonce, len(data))
    cipher = bytes(b ^ k for b, k in zip(data, stream))
    return _PREFIX + base64.urlsafe_b64encode(nonce + cipher).decode("ascii")


def decrypt_secret(value: str | None) -> str:
    """يفكّ ``enc$...``؛ أي قيمة أخرى (نص صريح/قديم) تُعاد كما هي."""
    if not value:
        return ""
    value = str(value)
    if not value.startswith(_PREFIX):
        return value
    try:
        raw = base64.urlsafe_b64decode(value[len(_PREFIX):].encode("ascii"))
        nonce, cipher = raw[:16], raw[16:]
        stream = _keystream(nonce, len(cipher))
        plain = bytes(b ^ k for b, k in zip(cipher, stream))
        return plain.decode("utf-8")
    except Exception:
        return ""
