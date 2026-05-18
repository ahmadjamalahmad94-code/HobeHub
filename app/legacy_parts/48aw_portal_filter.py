# 48aw_portal_filter.py
# يضيف فلتر "لديهم بوابة / بدون بوابة" لصفحة المستفيدين
# عبر monkey-patch لـ build_request_args_dict و build_beneficiary_filters

_orig_build_args = build_request_args_dict


def build_request_args_dict():
    d = _orig_build_args()
    from flask import request as _req
    d["has_portal"] = (_req.args.get("has_portal") or "").strip()
    return d


_orig_build_filters = build_beneficiary_filters


def build_beneficiary_filters(args_dict):
    filters, params = _orig_build_filters(args_dict)
    has_portal = (args_dict.get("has_portal") or "").strip()
    if has_portal == "yes":
        filters.append(
            "EXISTS (SELECT 1 FROM beneficiary_portal_accounts bpa WHERE bpa.beneficiary_id = b.id AND COALESCE(bpa.portal_membership_active, FALSE)=TRUE)"
        )
    elif has_portal == "no":
        filters.append(
            "NOT EXISTS (SELECT 1 FROM beneficiary_portal_accounts bpa WHERE bpa.beneficiary_id = b.id AND COALESCE(bpa.portal_membership_active, FALSE)=TRUE)"
        )
    return filters, params
