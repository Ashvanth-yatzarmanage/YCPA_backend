"""
Seed script — system roles + module permissions
Run once after fresh migration:
    python scripts/seed_roles.py
"""

import sys
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from ycpa.core.config import get_settings  # noqa: E402
from ycpa.models.roles import Role, RoleModulePermission  # noqa: E402

# ─── MODULES ──────────────────────────────────────────────────────────────────

PIM_MODULES = [
    "summary",
    "team",
    "document",
    "cost",
    "bcf",
    "ifc_viewer",
    "4d",
    "5d",
    "clash_detection",
]

AIM_MODULES = [
    "summary",
    "team",
    "document",
    "ifc_viewer",
]


# ─── ROLE DEFINITIONS ─────────────────────────────────────────────────────────
# Format: (name, product_type, module_permissions)
# module_permissions: dict of module -> {can_view, can_create, can_edit, can_delete, can_approve, can_share}
# Shorthand: True = True, False = False

def full():
    return dict(can_view=True, can_create=True, can_edit=True, can_delete=True, can_approve=True, can_share=True)

def view_only():
    return dict(can_view=True, can_create=False, can_edit=False, can_delete=False, can_approve=False, can_share=False)

def no_access():
    return dict(can_view=False, can_create=False, can_edit=False, can_delete=False, can_approve=False, can_share=False)

def contribute():
    return dict(can_view=True, can_create=True, can_edit=True, can_delete=False, can_approve=False, can_share=True)


SYSTEM_ROLES = [

    # ── PIM: Owner/Admin ──────────────────────────────────────────────────────
    {
        "name": "Owner/Admin",
        "product_type": "pim",
        "permissions": {
            "summary":         full(),
            "team":            full(),
            "document":        full(),
            "cost":            full(),
            "bcf":             full(),
            "ifc_viewer":      full(),
            "4d":              full(),
            "5d":              full(),
            "clash_detection": full(),
        }
    },

    # ── PIM: BIM Manager ─────────────────────────────────────────────────────
    {
        "name": "BIM Manager",
        "product_type": "pim",
        "permissions": {
            "summary":         view_only(),
            "team":            view_only(),
            "document":        full(),
            "cost":            full(),
            "bcf":             full(),
            "ifc_viewer":      full(),
            "4d":              full(),
            "5d":              full(),
            "clash_detection": full(),
        }
    },

    # ── PIM: BIM Coordinator ─────────────────────────────────────────────────
    {
        "name": "BIM Coordinator",
        "product_type": "pim",
        "permissions": {
            "summary":         view_only(),
            "team":            view_only(),
            "document":        contribute(),
            "cost":            view_only(),
            "bcf":             contribute(),
            "ifc_viewer":      view_only(),
            "4d":              view_only(),
            "5d":              view_only(),
            "clash_detection": view_only(),
        }
    },

    # ── PIM: BIM Modeller ────────────────────────────────────────────────────
    {
        "name": "BIM Modeller",
        "product_type": "pim",
        "permissions": {
            "summary":         view_only(),
            "team":            view_only(),
            "document":        contribute(),
            "cost":            no_access(),   # BIM Modeller cannot see cost
            "bcf":             view_only(),
            "ifc_viewer":      view_only(),
            "4d":              view_only(),
            "5d":              no_access(),
            "clash_detection": view_only(),
        }
    },

    # ── PIM: Viewer ──────────────────────────────────────────────────────────
    {
        "name": "Viewer",
        "product_type": "pim",
        "permissions": {
            "summary":         view_only(),
            "team":            view_only(),
            "document":        view_only(),
            "cost":            no_access(),
            "bcf":             no_access(),
            "ifc_viewer":      view_only(),
            "4d":              no_access(),
            "5d":              no_access(),
            "clash_detection": no_access(),
        }
    },

    # ── AIM: Owner/Admin ─────────────────────────────────────────────────────
    {
        "name": "Owner/Admin",
        "product_type": "aim",
        "permissions": {
            "summary":    full(),
            "team":       full(),
            "document":   full(),
            "ifc_viewer": full(),
        }
    },

    # ── AIM: Viewer ──────────────────────────────────────────────────────────
    {
        "name": "Viewer",
        "product_type": "aim",
        "permissions": {
            "summary":    view_only(),
            "team":       view_only(),
            "document":   view_only(),
            "ifc_viewer": view_only(),
        }
    },
]


# ─── SEED ─────────────────────────────────────────────────────────────────────

def seed():
    settings = get_settings()
    engine = create_engine(str(settings.DATABASE_URL_SYNC))

    with Session(engine) as session:

        # check if already seeded
        existing = session.query(Role).filter_by(is_system=True).count()
        if existing > 0:
            print(f"Already seeded ({existing} system roles found). Skipping.")
            return

        total_roles = 0
        total_perms = 0

        for role_def in SYSTEM_ROLES:
            role = Role(
                id=uuid.uuid4(),
                name=role_def["name"],
                product_type=role_def["product_type"],
                is_system=True,
                is_editable=True,
                is_active=True,
                created_by_type="system",
                workspace_id=None,
            )
            session.add(role)
            session.flush()  # get role.id before adding permissions

            for module, perms in role_def["permissions"].items():
                perm = RoleModulePermission(
                    id=uuid.uuid4(),
                    role_id=role.id,
                    module=module,
                    can_view=perms["can_view"],
                    can_create=perms["can_create"],
                    can_edit=perms["can_edit"],
                    can_delete=perms["can_delete"],
                    can_approve=perms["can_approve"],
                    can_share=perms["can_share"],
                )
                session.add(perm)
                total_perms += 1

            total_roles += 1
            print(f"  + {role_def['product_type'].upper()}: {role_def['name']} ({len(role_def['permissions'])} modules)")

        session.commit()
        print(f"\nDone. {total_roles} roles, {total_perms} module permission rows inserted.")


if __name__ == "__main__":
    seed()
