"""
Sales Person Manager — ES_USER.sales_person CRUD (MariaDB)
Connection settings: info_config/mariadb_es_user.json
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "info_config" / "mariadb_es_user.json"

sys.path.insert(0, str(BASE_DIR))
from utils.access_logger import log_access

st.set_page_config(
    page_title="Sales Person Information",
    page_icon="👤",
    layout="wide",
    initial_sidebar_state="expanded",
)
log_access("Sales Person Information")

st.markdown(
    """
<style>
    .main { background: linear-gradient(180deg, #eaf0f6 0%, #f4f6fa 50%, #f0f2f6 100%); }
    .block-container { padding-top: 1.2rem; padding-bottom: 2.5rem; }

    .sp-hero {
        background: linear-gradient(135deg, #1a4971 0%, #2d6ea8 50%, #3d8fd4 100%);
        color: #fff;
        border-radius: 16px;
        padding: 1.2rem 1.75rem;
        margin-bottom: 1.25rem;
        box-shadow: 0 10px 36px rgba(26, 73, 113, 0.32);
    }
    .sp-hero h1 { margin: 0; font-size: 1.65rem; font-weight: 800; letter-spacing: -0.02em; }
    .sp-hero p  { margin: 0.4rem 0 0; opacity: 0.9; font-size: 0.92rem; }

    .sp-card {
        background: #fff;
        border-radius: 12px;
        padding: 14px 18px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.07);
        border-left: 4px solid #2d6ea8;
        text-align: center;
    }
    .sp-card .lbl {
        font-size: 0.70rem; text-transform: uppercase;
        letter-spacing: 0.08em; color: #889; font-weight: 700;
    }
    .sp-card .val { font-size: 1.4rem; font-weight: 800; color: #1a1a2e; margin-top: 4px; }

    .sp-section {
        font-size: 1.05rem; font-weight: 700; color: #1a4971;
        margin: 1.1rem 0 0.6rem; padding-bottom: 6px;
        border-bottom: 2px solid #c5d8ed;
    }
    div[data-testid="stTabs"] button { font-weight: 600; }
</style>
""",
    unsafe_allow_html=True,
)

# ── DB helpers ─────────────────────────────────────────────────────────────────

def load_db_config() -> dict:
    if not CONFIG_PATH.is_file():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


@contextmanager
def db_connection():
    cfg = load_db_config()
    conn = __import__("pymysql").connect(
        host=cfg["host"],
        port=int(cfg.get("port", 3306)),
        user=cfg["user"],
        password=cfg.get("password", ""),
        database=cfg["database"],
        charset="utf8mb4",
        autocommit=False,
    )
    try:
        yield conn
    finally:
        conn.close()


DDL = """
CREATE TABLE IF NOT EXISTS sales_person (
    id             INT UNSIGNED   NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name           VARCHAR(200)   NOT NULL,
    email          VARCHAR(200)   NOT NULL DEFAULT '',
    phone          VARCHAR(50)    NOT NULL DEFAULT '',
    department     VARCHAR(200)   NOT NULL DEFAULT '',
    main_customer  VARCHAR(200)   NOT NULL DEFAULT '',
    active         TINYINT(1)     NOT NULL DEFAULT 1,
    created_at     DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_name   (name),
    KEY idx_active (active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

COLS = ["id", "name", "department", "main_customer", "phone", "email", "active", "created_at"]


def ensure_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute("""
            ALTER TABLE sales_person
            ADD COLUMN IF NOT EXISTS main_customer VARCHAR(200) NOT NULL DEFAULT ''
            AFTER department
        """)
    conn.commit()


def fetch_all(conn) -> pd.DataFrame:
    sql = """
    SELECT id, name, email, phone, department, main_customer, active, created_at
    FROM sales_person
    ORDER BY active DESC, name ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=COLS)
    return pd.DataFrame(rows, columns=COLS)


def insert_person(conn, row: dict) -> int:
    sql = """
    INSERT INTO sales_person (name, email, phone, department, main_customer, active)
    VALUES (%(name)s, %(email)s, %(phone)s, %(department)s, %(main_customer)s, %(active)s)
    """
    with conn.cursor() as cur:
        cur.execute(sql, row)
        new_id = cur.lastrowid
    conn.commit()
    return int(new_id) if new_id else 0


def update_person(conn, row: dict) -> None:
    sql = """
    UPDATE sales_person
    SET name=%(name)s, email=%(email)s, phone=%(phone)s,
        department=%(department)s, main_customer=%(main_customer)s, active=%(active)s
    WHERE id=%(id)s
    """
    with conn.cursor() as cur:
        n = cur.execute(sql, row)
    conn.commit()
    if n == 0:
        raise ValueError("Row not found.")


def delete_person(conn, row_id: int) -> None:
    with conn.cursor() as cur:
        n = cur.execute("DELETE FROM sales_person WHERE id=%s", (row_id,))
    conn.commit()
    if n == 0:
        raise ValueError("Row not found.")


# ── Load ───────────────────────────────────────────────────────────────────────

st.markdown(
    """
    <div class="sp-hero">
      <h1>👤 Sales Person Manager</h1>
      <p>ES_USER · sales_person — add, edit, and deactivate sales owners used in Forecast Planner.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

try:
    with db_connection() as conn:
        ensure_table(conn)
        df = fetch_all(conn)
except Exception as e:
    st.error(f"Database connection failed: {e}")
    st.info("Check `info_config/mariadb_es_user.json` and retry.")
    st.stop()

# ── KPI cards ─────────────────────────────────────────────────────────────────

n_total  = len(df)
n_active = int(df["active"].apply(lambda v: int(v) if pd.notna(v) else 0).sum()) if n_total else 0
n_dept   = int(df["department"].fillna("").astype(str).str.strip().replace("", pd.NA).nunique(dropna=True)) if n_total else 0

k1, k2, k3 = st.columns(3)
for col, lbl, val in [
    (k1, "Total", f"{n_total:,}"),
    (k2, "Active", f"{n_active:,}"),
    (k3, "Departments", f"{n_dept:,}"),
]:
    with col:
        st.markdown(
            f'<div class="sp-card"><div class="lbl">{lbl}</div>'
            f'<div class="val">{val}</div></div>',
            unsafe_allow_html=True,
        )

st.markdown("<br>", unsafe_allow_html=True)

# ── Tabs ───────────────────────────────────────────────────────────────────────

st.markdown('<p class="sp-section">📝 Manage sales persons</p>', unsafe_allow_html=True)
tab_add, tab_edit = st.tabs(["➕ Add new", "✏️ Edit / Deactivate"])

_ADD_RATIO = [1.2, 0.9, 1.1, 0.9, 0.9, 0.6, 0.9]

with tab_add:
    with st.form("sp_insert", clear_on_submit=True):
        h1, h2, h3, h4, h5, h6, h7 = st.columns(_ADD_RATIO)
        with h1: st.caption("Name *")
        with h2: st.caption("Department")
        with h3: st.caption("Main Customer")
        with h4: st.caption("Phone")
        with h5: st.caption("Email")
        with h6: st.caption("Active")
        with h7: st.caption("save")

        c1, c2, c3, c4, c5, c6, c7 = st.columns(_ADD_RATIO)
        with c1:
            new_name = st.text_input("Name *", placeholder="e.g. John Kim",
                                     label_visibility="collapsed")
        with c2:
            new_dept = st.text_input("Department", placeholder="e.g. OE Sales",
                                     label_visibility="collapsed")
        with c3:
            new_main_cust = st.text_input("Main Customer", placeholder="e.g. Acme Corp",
                                          label_visibility="collapsed")
        with c4:
            new_phone = st.text_input("Phone", placeholder="+1-xxx-xxx-xxxx",
                                      label_visibility="collapsed")
        with c5:
            new_email = st.text_input("Email", placeholder="john@example.com",
                                      label_visibility="collapsed")
        with c6:
            new_active = st.checkbox("Active", value=True, label_visibility="visible")
        with c7:
            add_btn = st.form_submit_button("💾 Save", type="primary", use_container_width=True)
        if add_btn:
            if not new_name.strip():
                st.error("Name is required.")
            else:
                try:
                    with db_connection() as conn:
                        nid = insert_person(conn, {
                            "name": new_name.strip(),
                            "email": new_email.strip(),
                            "phone": new_phone.strip(),
                            "department": new_dept.strip(),
                            "main_customer": new_main_cust.strip(),
                            "active": 1 if new_active else 0,
                        })
                    st.success(f"Saved — id **{nid}**.")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Failed: {ex}")

with tab_edit:
    if df.empty:
        st.info("No sales persons yet. Add one first.")
    else:
        # ── 필터 패널 ─────────────────────────────────────────────────────────
        st.markdown(
            "<div style='font-size:0.82rem;font-weight:700;color:#1a4971;"
            "margin-bottom:6px;'>🔍 Filter rows</div>",
            unsafe_allow_html=True,
        )
        sf1, sf2, sf3 = st.columns([1.4, 1.2, 0.8])
        with sf1:
            flt_name = st.text_input("Name", placeholder="Type to filter…",
                                     key="sp_flt_name", label_visibility="visible")
        with sf2:
            dept_opts = ["(All)"] + sorted(
                df["department"].fillna("").astype(str).str.strip()
                .replace("", pd.NA).dropna().unique().tolist()
            )
            flt_dept = st.selectbox("Department", options=dept_opts,
                                    key="sp_flt_dept", label_visibility="visible")
        with sf3:
            flt_status = st.selectbox("Status", options=["(All)", "✅ Active", "⛔ Inactive"],
                                      key="sp_flt_status", label_visibility="visible")

        # 필터 적용
        view = df.copy()
        view["id"] = view["id"].astype(int)
        if flt_name.strip():
            view = view[view["name"].astype(str)
                        .str.contains(flt_name.strip(), case=False, na=False)]
        if flt_dept != "(All)":
            view = view[view["department"].astype(str).str.strip() == flt_dept]
        if flt_status == "✅ Active":
            view = view[view["active"].apply(lambda v: int(v) if pd.notna(v) else 0) == 1]
        elif flt_status == "⛔ Inactive":
            view = view[view["active"].apply(lambda v: int(v) if pd.notna(v) else 0) == 0]

        view = view.sort_values(["active", "name"], ascending=[False, True])

        st.caption(f"**{len(view):,}** row(s) match · click a row to select it for editing")

        # ── 클릭 선택 테이블 ──────────────────────────────────────────────────
        tbl_cols = ["id", "name", "department", "main_customer", "email", "phone", "active"]
        tbl_cols = [c for c in tbl_cols if c in view.columns]
        tbl_view = view[tbl_cols].copy()
        tbl_view["active"] = tbl_view["active"].apply(
            lambda v: "✅ Active" if int(v) else "⛔ Inactive"
        )

        event = st.dataframe(
            tbl_view.reset_index(drop=True),
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "id":            None,
                "name":          st.column_config.TextColumn("Name"),
                "department":    st.column_config.TextColumn("Department"),
                "main_customer": st.column_config.TextColumn("Main Customer"),
                "email":         st.column_config.TextColumn("Email"),
                "phone":         st.column_config.TextColumn("Phone"),
                "active":        st.column_config.TextColumn("Status"),
            },
            key="sp_edit_table",
        )

        selected_rows = (
            event.selection.get("rows", [])
            if event and hasattr(event, "selection") else []
        )
        pick = None
        if selected_rows:
            sel_idx = selected_rows[0]
            id_view = view[["id"]].reset_index(drop=True)
            if sel_idx < len(id_view):
                pick = int(id_view.iloc[sel_idx]["id"])

        if pick is None:
            st.info("👆 Click a row above to load it into the edit form.")
        else:
            rec = df.loc[df["id"].astype(int) == pick].iloc[0]
            p = pick

            st.markdown(
                f"<div style='background:#e8f0fb;border-left:4px solid #2d6ea8;"
                f"border-radius:8px;padding:8px 14px;margin:10px 0 6px;"
                f"font-size:0.88rem;color:#1a4971;font-weight:600;'>"
                f"✏️ Editing ID <b>#{pick}</b> — {rec['name']} "
                f"[{rec['department'] or '—'}]</div>",
                unsafe_allow_html=True,
            )

            with st.form(f"sp_update_{p}"):
                eh1, eh2, eh3, eh4, eh5, eh6, eh7 = st.columns(_ADD_RATIO)
                with eh1: st.caption("Name *")
                with eh2: st.caption("Department")
                with eh3: st.caption("Main Customer")
                with eh4: st.caption("Phone")
                with eh5: st.caption("Email")
                with eh6: st.caption("Active")
                with eh7: st.caption("actions")

                ec1, ec2, ec3, ec4, ec5, ec6, ec7 = st.columns(_ADD_RATIO)
                with ec1:
                    ename = st.text_input("Name *", value=str(rec["name"]),
                                          key=f"up_name_{p}", label_visibility="collapsed")
                with ec2:
                    edept = st.text_input("Department", value=str(rec["department"]),
                                          key=f"up_dept_{p}", label_visibility="collapsed")
                with ec3:
                    _mc_val = str(rec["main_customer"]) if "main_customer" in rec.index and pd.notna(rec["main_customer"]) else ""
                    emain_cust = st.text_input("Main Customer", value=_mc_val,
                                               key=f"up_main_cust_{p}", label_visibility="collapsed",
                                               placeholder="e.g. Acme Corp")
                with ec4:
                    ephone = st.text_input("Phone", value=str(rec["phone"]),
                                           key=f"up_phone_{p}", label_visibility="collapsed")
                with ec5:
                    eemail = st.text_input("Email", value=str(rec["email"]),
                                           key=f"up_email_{p}", label_visibility="collapsed")
                with ec6:
                    eactive = st.checkbox("Active", value=bool(int(rec["active"])),
                                          key=f"up_active_{p}")
                with ec7:
                    btn_l, btn_r = st.columns(2, gap="small")
                    with btn_l:
                        save_btn = st.form_submit_button("💾 Save", type="primary",
                                                         use_container_width=True)
                    with btn_r:
                        del_btn = st.form_submit_button("🗑 Del", type="secondary",
                                                        use_container_width=True)

            if del_btn:
                try:
                    with db_connection() as conn:
                        delete_person(conn, pick)
                    st.success(f"ID {pick} deleted.")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Delete failed: {ex}")
            elif save_btn:
                if not ename.strip():
                    st.error("Name is required.")
                else:
                    try:
                        with db_connection() as conn:
                            update_person(conn, {
                                "id": pick,
                                "name": ename.strip(),
                                "email": eemail.strip(),
                                "phone": ephone.strip(),
                                "department": edept.strip(),
                                "main_customer": emain_cust.strip(),
                                "active": 1 if eactive else 0,
                            })
                        st.success(f"ID {pick} updated.")
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Save failed: {ex}")

# ── Full list ──────────────────────────────────────────────────────────────────

st.markdown('<p class="sp-section">📋 Sales Persons Status</p>', unsafe_allow_html=True)
if df.empty:
    st.write("No records.")
else:
    show = df.copy()
    show["id"]     = show["id"].astype(int)
    show["active"] = show["active"].apply(lambda v: "✅ Active" if int(v) else "⛔ Inactive")
    st.dataframe(
        show,
        use_container_width=True,
        hide_index=True,
        column_config={
            "id":            None,
            "name":          st.column_config.TextColumn("Name"),
            "department":    st.column_config.TextColumn("Department"),
            "main_customer": st.column_config.TextColumn("Main Customer"),
            "email":         st.column_config.TextColumn("Email"),
            "phone":         st.column_config.TextColumn("Phone"),
            "active":        st.column_config.TextColumn("Status"),
            "created_at":    st.column_config.DatetimeColumn("Created at"),
        },
    )

st.markdown("---")
st.caption(f"Database: **ES_USER** · table **sales_person** · config **{CONFIG_PATH.name}**")
st.markdown(
    "<div style='text-align:center;color:#aaa;font-size:.78rem;padding:10px;'>"
    "© 2026 Hankook &amp; Company ES America Corp. &nbsp;|&nbsp; Sales Person Information"
    "</div>",
    unsafe_allow_html=True,
)
