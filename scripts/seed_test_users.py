"""seed_test_users.py — يُنشئ مشتركَين تجريبيَّين (بطاقات + يوزر).

التشغيل من جذر المشروع:
    python scripts/seed_test_users.py

سيُنشئ:
    1) مشترك بطاقات (توجيهي)  — رقم الجوال: 0599100100  / كلمة المرور: test1234
    2) مشترك يوزر  (جامعي)    — رقم الجوال: 0599200200  / كلمة المرور: test1234
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
from pathlib import Path

# نستخدم werkzeug مثلما يفعل التطبيق الحقيقي — هذا الـ hash يقبله verify_portal_password
from werkzeug.security import generate_password_hash


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("HOBEHUB_LOCAL_DB_PATH", ROOT / "instance" / "hobehub_local_demo.sqlite3"))


PHONE_CARDS = "0599100100"   # username = phone (هذا ما يبحث عنه login)
PHONE_USERS = "0599200200"
PWD = "test1234"


def main() -> None:
    if not DB_PATH.exists():
        print(f"❌ DB not found at: {DB_PATH}")
        print("   شغّل التطبيق مرة واحدة أولاً ليُنشئ القاعدة، ثم أعد تشغيل هذا السكريبت.")
        sys.exit(1)

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    def ensure_beneficiary(rec: dict) -> int:
        row = cur.execute(
            "SELECT id FROM beneficiaries WHERE phone=? LIMIT 1", (rec["phone"],)
        ).fetchone()
        if row:
            return row["id"]
        cols = list(rec.keys())
        ph = ",".join(["?"] * len(cols))
        cur.execute(
            f"INSERT INTO beneficiaries ({','.join(cols)}) VALUES ({ph})",
            tuple(rec[c] for c in cols),
        )
        return cur.lastrowid

    def ensure_portal(beneficiary_id: int, username: str, plain_password: str) -> int:
        pw_hash = generate_password_hash(plain_password)
        existing = cur.execute(
            "SELECT id FROM beneficiary_portal_accounts "
            "WHERE beneficiary_id=? OR username=? LIMIT 1",
            (beneficiary_id, username),
        ).fetchone()
        if existing:
            cur.execute(
                """UPDATE beneficiary_portal_accounts
                   SET beneficiary_id=?, username=?, password_hash=?,
                       is_active=1, portal_membership_active=1, must_set_password=0,
                       activated_at=CURRENT_TIMESTAMP,
                       failed_login_attempts=0, locked_until=NULL,
                       updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (beneficiary_id, username, pw_hash, existing["id"]),
            )
            return existing["id"]
        cur.execute(
            """INSERT INTO beneficiary_portal_accounts
               (beneficiary_id, username, password_hash, is_active,
                portal_membership_active, must_set_password, activated_at)
               VALUES (?, ?, ?, 1, 1, 0, CURRENT_TIMESTAMP)""",
            (beneficiary_id, username, pw_hash),
        )
        return cur.lastrowid

    # ── 1) مشترك بطاقات — توجيهي ─────────────────────────────────
    cards_id = ensure_beneficiary({
        "user_type": "tawjihi",
        "first_name": "أحمد", "second_name": "محمد",
        "third_name": "علي",  "fourth_name": "حسن",
        "full_name": "أحمد محمد علي حسن",
        "search_name": "أحمد محمد علي حسن " + PHONE_CARDS,
        "phone": PHONE_CARDS,
        "tawjihi_year": "2024",
        "tawjihi_branch": "علمي",
        "notes": "حساب تجريبي - مشترك بطاقات",
    })
    ensure_portal(cards_id, PHONE_CARDS, PWD)

    # ── 2) مشترك يوزر — جامعي ─────────────────────────────────────
    users_id = ensure_beneficiary({
        "user_type": "university",
        "first_name": "ليلى", "second_name": "خالد",
        "third_name": "إبراهيم", "fourth_name": "النجار",
        "full_name": "ليلى خالد إبراهيم النجار",
        "search_name": "ليلى خالد إبراهيم النجار " + PHONE_USERS,
        "phone": PHONE_USERS,
        "university_name": "الجامعة الإسلامية",
        "university_college": "تكنولوجيا المعلومات",
        "university_specialization": "هندسة برمجيات",
        "university_internet_method": "يوزر إنترنت",
        "notes": "حساب تجريبي - مشترك يوزر",
    })
    ensure_portal(users_id, PHONE_USERS, PWD)

    # ── radius_account للمشترك الـ user (اختياري — لإظهار اسم RADIUS) ──
    md5 = hashlib.md5(PWD.encode("utf-8")).hexdigest()
    row = cur.execute(
        "SELECT id FROM beneficiary_radius_accounts WHERE beneficiary_id=? LIMIT 1",
        (users_id,),
    ).fetchone()
    if not row:
        cur.execute(
            """INSERT INTO beneficiary_radius_accounts
               (beneficiary_id, external_username, current_profile_name, status,
                password_md5, plain_password, sync_status)
               VALUES (?, ?, ?, 'active', ?, ?, 'pending')""",
            (users_id, "layla_net", "3M-Standard", md5, PWD),
        )
    else:
        cur.execute(
            """UPDATE beneficiary_radius_accounts
               SET external_username='layla_net',
                   current_profile_name='3M-Standard',
                   status='active',
                   password_md5=?, plain_password=?, sync_status='pending',
                   updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (md5, PWD, row["id"]),
        )

    con.commit()

    print()
    print("═══════════════════════════════════════════")
    print("  ✓ تم إنشاء الحسابات التجريبية")
    print("═══════════════════════════════════════════")
    print()
    print("  ◆ مشترك بطاقات (توجيهي)")
    print(f"    رقم الجوال:    {PHONE_CARDS}")
    print(f"    كلمة المرور:   {PWD}")
    print(f"    بعد الدخول:    /cards")
    print()
    print("  ◆ مشترك يوزر (جامعي)")
    print(f"    رقم الجوال:    {PHONE_USERS}")
    print(f"    كلمة المرور:   {PWD}")
    print(f"    بعد الدخول:    /users/account")
    print()
    print("  → افتح: http://127.0.0.1:5000/user/login")
    print()

    # تحقق نهائي
    print("── تأكيد نهائي من DB ──")
    for u in (PHONE_CARDS, PHONE_USERS):
        r = cur.execute(
            """SELECT bp.username, bp.is_active, bp.must_set_password,
                      substr(bp.password_hash, 1, 14) AS hash_prefix,
                      b.full_name, b.user_type
               FROM beneficiary_portal_accounts bp
               JOIN beneficiaries b ON b.id = bp.beneficiary_id
               WHERE bp.username=?""",
            (u,),
        ).fetchone()
        if r:
            print(
                f"  ✓ {r['username']}  active={r['is_active']}  "
                f"must_set={r['must_set_password']}  hash={r['hash_prefix']}…  "
                f"type={r['user_type']}  name={r['full_name']}"
            )
        else:
            print(f"  ❌ {u} not found!")

    con.close()


if __name__ == "__main__":
    main()
