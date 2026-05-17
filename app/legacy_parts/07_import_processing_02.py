# Continued split from 07_import_processing.py lines 133-278. Loaded by app.legacy.


def run_import_task(task_id: str, content: str):
    update_import_task(task_id, status="running", started_at=_now_text(), current_step="قراءة الملف")
    append_import_log(task_id, "بدأت مهمة الاستيراد في الخلفية.")
    conn = None
    cur = None
    try:
        reader = csv.DictReader(io.StringIO(content))
        if not reader.fieldnames:
            finalize_import_task(task_id, "failed", "الملف فارغ أو غير صالح.")
            append_import_log(task_id, "تعذر العثور على رؤوس الأعمدة داخل الملف.", is_error=True)
            return

        normalized_rows = []
        seen_file_keys = set()
        task_meta = get_import_task(task_id) or {}
        import_username = clean_csv_value(task_meta.get("username")) or "استيراد CSV"
        import_account_id = task_meta.get("account_id")
        for idx, row in enumerate(reader, start=2):
            data = _normalize_import_row(row)
            data["added_by_username"] = import_username
            data["added_by_account_id"] = import_account_id
            dedupe_key = (data.get("phone") or "", data.get("full_name") or "", data.get("user_type") or "")
            if dedupe_key in seen_file_keys:
                append_import_log(task_id, f"تم تجاوز السطر {idx} لأنه مكرر داخل نفس الملف.", is_error=True)
                update_import_task(task_id, skipped=(get_import_task(task_id)["skipped"] + 1))
                continue
            seen_file_keys.add(dedupe_key)
            normalized_rows.append((idx, data))

        total = len(normalized_rows)
        update_import_task(task_id, total=total, current_step="تحليل البيانات")
        append_import_log(task_id, f"تمت قراءة الملف بنجاح. عدد السجلات القابلة للمعالجة: {total}.")
        if total == 0:
            finalize_import_task(task_id, "completed", "لا توجد سجلات صالحة للاستيراد.")
            return

        phone_map, name_type_map = _build_existing_lookup()
        inserts, updates = split_import_operations(normalized_rows, phone_map, name_type_map)

        append_import_log(task_id, f"تجهيز العملية: {len(inserts)} سجل جديد، {len(updates)} سجل للتحديث.")
        update_import_task(task_id, current_step="الاتصال بقاعدة البيانات")

        conn = get_connection()
        cur = conn.cursor()

        def process_batches(items, is_update: bool):
            inserted_count = 0
            updated_count = 0
            label = "تحديث" if is_update else "إضافة"
            for start in range(0, len(items), IMPORT_BATCH_SIZE):
                batch = items[start:start + IMPORT_BATCH_SIZE]
                batch_records = [data for _, data in batch]
                ok_count = 0
                try:
                    if is_update:
                        _bulk_update_beneficiaries(cur, batch_records)
                    else:
                        _bulk_insert_beneficiaries(cur, batch_records)
                    conn.commit()
                    ok_count = len(batch)
                except Exception as exc:
                    conn.rollback()
                    append_import_log(task_id, f"فشل {label} دفعة من {len(batch)} سجلات، سيتم التحويل إلى معالجة تفصيلية: {exc}", is_error=True)
                    ok_count = _process_rows_fallback(cur, task_id, label, batch, is_update)
                    conn.commit()
                if is_update:
                    updated_count += ok_count
                else:
                    inserted_count += ok_count
                task_snapshot = get_import_task(task_id)
                update_import_task(
                    task_id,
                    processed=(task_snapshot["processed"] + len(batch)),
                    inserted=(task_snapshot["inserted"] + (0 if is_update else ok_count)),
                    updated=(task_snapshot["updated"] + (ok_count if is_update else 0)),
                    current_step=f"{label} البيانات... {min(start + len(batch), len(items))}/{len(items)}"
                )
                append_import_log(task_id, f"{label} دفعة: {min(start + len(batch), len(items))}/{len(items)}. نجاح {ok_count} من {len(batch)}.")
            return inserted_count, updated_count

        total_inserted = 0
        total_updated = 0
        if inserts:
            ins, _ = process_batches(inserts, is_update=False)
            total_inserted += ins
            update_import_task(task_id, inserted=total_inserted)
        if updates:
            _, upd = process_batches(updates, is_update=True)
            total_updated += upd
            update_import_task(task_id, updated=total_updated)

        task_snapshot = get_import_task(task_id)
        msg = f"اكتملت المعالجة. تمت إضافة {task_snapshot['inserted']} وتحديث {task_snapshot['updated']} مع {task_snapshot['error_count']} خطأ."
        finalize_import_task(task_id, "completed", msg)
        append_import_log(task_id, msg)

        if task_snapshot.get("account_id"):
            conn2 = get_connection()
            cur2 = conn2.cursor()
            try:
                cur2.execute(
                    """
                    INSERT INTO audit_logs (account_id, username_snapshot, action_type, target_type, target_id, details)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    """,
                    [task_snapshot.get("account_id"), task_snapshot.get("username"), "import", "beneficiary", None, msg]
                )
                conn2.commit()
            finally:
                cur2.close()
                release_connection(conn2)
    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        append_import_log(task_id, f"توقفت المهمة بسبب خطأ عام: {exc}", is_error=True)
        finalize_import_task(task_id, "failed", f"فشلت المعالجة: {exc}")
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            release_connection(conn)


def launch_import_task(task_id: str, content: str):
    thread = threading.Thread(target=run_import_task, args=(task_id, content), daemon=True)
    thread.start()
