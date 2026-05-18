"""
Material & Customer Manager — ES_USER.material_customer CRUD (MariaDB)
Oracle ESLPPROD:
  - material_code  ← ES_IF_MATERIAL.MATNR  (10-char, distinct)
  - customer       ← ES_IP_CUSTOMER.NAME1  (distinct)
  - part_number    ← ES_IF_MATERIAL.A003   (auto-filled by material_code)
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent.parent
MARIA_CFG  = BASE_DIR / "info_config" / "mariadb_es_user.json"
ORACLE_CFG = BASE_DIR / "info_config" / "eslpprod_db.json"

sys.path.insert(0, str(BASE_DIR))
from utils.access_logger import log_access

# 폼에서 직접 입력하는 컬럼 (material_code·part_number 제외)
FORM_COLS = ["segment", "channel", "customer", "customer_code",
             "category", "product", "group_size", "cca"]
# 전체 데이터 컬럼
DATA_COLS  = ["material_code", "segment", "channel", "customer", "customer_code",
              "category", "product", "group_size", "cca", "part_number"]

COL_LABELS = {
    "material_code": "🔩 Material Code",
    "segment":       "📂 Segment",
    "channel":       "📡 Channel",
    "customer":      "🏢 Customer",
    "customer_code": "🔑 Customer Code",
    "category":      "🗂 Category",
    "product":       "📦 Product",
    "group_size":    "📐 Group Size",
    "cca":           "🏷 CCA",
    "part_number":   "🔖 Part Number",
}

st.set_page_config(
    page_title="Material & Customer",
    page_icon="🔩",
    layout="wide",
    initial_sidebar_state="expanded",
)
log_access("Master: Material & Customer")

st.markdown("""
<style>
    .main { background: linear-gradient(180deg, #edf2f0 0%, #f4f7f5 50%, #f0f2f0 100%); }
    .block-container { padding-top: 1.2rem; padding-bottom: 2.5rem; }

    .mc-hero {
        background: linear-gradient(135deg, #1a4a35 0%, #2d7a55 50%, #3da872 100%);
        color: #fff; border-radius: 16px; padding: 1.2rem 1.75rem;
        margin-bottom: 1.25rem; box-shadow: 0 10px 36px rgba(26,74,53,0.32);
    }
    .mc-hero h1 { margin:0; font-size:1.65rem; font-weight:800; letter-spacing:-0.02em; }
    .mc-hero p  { margin:0.4rem 0 0; opacity:0.9; font-size:0.92rem; }

    .mc-card {
        background:#fff; border-radius:12px; padding:14px 18px;
        box-shadow:0 4px 16px rgba(0,0,0,0.07);
        border-left:4px solid #2d7a55; text-align:center;
    }
    .mc-card .lbl {
        font-size:0.70rem; text-transform:uppercase;
        letter-spacing:0.08em; color:#889; font-weight:700;
    }
    .mc-card .val { font-size:1.4rem; font-weight:800; color:#1a1a2e; margin-top:4px; }

    .mc-section {
        font-size:1.05rem; font-weight:700; color:#1a4a35;
        margin:1.1rem 0 0.6rem; padding-bottom:6px;
        border-bottom:2px solid #c0d9cc;
    }
    .pn-box {
        background:#f0faf4; border:1.5px solid #2d7a55; border-radius:8px;
        padding:6px 12px; font-size:0.95rem; font-weight:700; color:#1a4a35;
        min-height:38px; display:flex; align-items:center;
    }
    div[data-testid="stTabs"] button { font-weight:600; }
</style>
""", unsafe_allow_html=True)


# ── Oracle helpers ─────────────────────────────────────────────────────────────

def _load_oracle_cfg() -> dict:
    with open(ORACLE_CFG, encoding="utf-8") as f:
        return json.load(f)


@contextmanager
def oracle_connection():
    cfg = _load_oracle_cfg()
    try:
        import oracledb
    except ImportError:
        raise ImportError("oracledb not installed — run: pip install oracledb")
    conn = oracledb.connect(
        user=cfg["user"],
        password=cfg["password"],
        dsn=f"{cfg['host']}:{cfg['port']}/{cfg['service_name']}",
    )
    try:
        yield conn
    finally:
        conn.close()


@st.cache_data(ttl=3600, show_spinner="Loading material codes from Oracle…")
def fetch_oracle_materials() -> list[str]:
    """ES_IF_MATERIAL.MATNR — 앞 10자리, 중복 제거, 정렬."""
    sql = """
        SELECT DISTINCT TRIM(SUBSTR(MATNR, 1, 10)) AS MATNR
        FROM ESLPPROD.ES_IF_MATERIAL
        WHERE MATNR IS NOT NULL
        ORDER BY 1
    """
    try:
        with oracle_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql)
            return [str(r[0]) for r in cur.fetchall() if r[0]]
    except Exception as e:
        st.warning(f"Oracle material fetch failed: {e}")
        return []


@st.cache_data(ttl=3600, show_spinner="Loading customers from Oracle…")
def fetch_oracle_customers() -> tuple[list[str], list[str], dict[str, str], dict[str, str]]:
    """ES_IF_CUSTOMER — NAME1(고객명) + PARTNER(코드) 쌍 로드.
    Returns: (name_list, code_list, name→code dict, code→name dict)
    """
    sql = """
        SELECT TRIM(NAME1) AS NAME1, TRIM(PARTNER) AS PARTNER
        FROM ESLPPROD.ES_IF_CUSTOMER
        WHERE NAME1 IS NOT NULL AND PARTNER IS NOT NULL
        ORDER BY NAME1
    """
    try:
        with oracle_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql)
            rows = cur.fetchall()
        seen_names, seen_codes = set(), set()
        name_list, code_list = [], []
        name_to_code, code_to_name = {}, {}
        for name, code in rows:
            name, code = str(name).strip(), str(code).strip()
            if not name or not code:
                continue
            name_to_code[name] = code
            code_to_name[code] = name
            if name not in seen_names:
                name_list.append(name)
                seen_names.add(name)
            if code not in seen_codes:
                code_list.append(code)
                seen_codes.add(code)
        code_list_sorted = sorted(code_list)
        return name_list, code_list_sorted, name_to_code, code_to_name
    except Exception as e:
        st.warning(f"Oracle customer fetch failed: {e}")
        return [], [], {}, {}


@st.cache_data(ttl=3600)
def fetch_part_number(matnr: str) -> str:
    """ES_IF_MATERIAL.A003 for the given MATNR (10-char). Returns '' if not found."""
    if not matnr:
        return ""
    sql = """
        SELECT A003
        FROM ESLPPROD.ES_IF_MATERIAL
        WHERE TRIM(SUBSTR(MATNR, 1, 10)) = :matnr
        AND ROWNUM = 1
    """
    try:
        with oracle_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, {"matnr": matnr})
            row = cur.fetchone()
            return str(row[0]).strip() if row and row[0] else ""
    except Exception as e:
        st.warning(f"Oracle part number fetch failed: {e}")
        return ""


# ── MariaDB helpers ────────────────────────────────────────────────────────────

def _load_maria_cfg() -> dict:
    with open(MARIA_CFG, encoding="utf-8") as f:
        return json.load(f)


@contextmanager
def db_connection():
    cfg = _load_maria_cfg()
    import pymysql
    conn = pymysql.connect(
        host=cfg["host"], port=int(cfg.get("port", 3306)),
        user=cfg["user"], password=cfg.get("password", ""),
        database=cfg["database"], charset="utf8mb4", autocommit=False,
    )
    try:
        yield conn
    finally:
        conn.close()


def ensure_table(conn) -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS material_customer (
        id            INT UNSIGNED  NOT NULL AUTO_INCREMENT PRIMARY KEY,
        material_code VARCHAR(200)  NOT NULL DEFAULT '',
        segment       VARCHAR(200)  NOT NULL DEFAULT '',
        channel       VARCHAR(200)  NOT NULL DEFAULT '',
        customer      VARCHAR(200)  NOT NULL DEFAULT '',
        category      VARCHAR(200)  NOT NULL DEFAULT '',
        product       VARCHAR(200)  NOT NULL DEFAULT '',
        group_size    VARCHAR(200)  NOT NULL DEFAULT '',
        cca           INT           NOT NULL DEFAULT 0,
        part_number   VARCHAR(200)  NOT NULL DEFAULT '',
        created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY idx_material (material_code),
        KEY idx_customer (customer)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """
    with conn.cursor() as cur:
        cur.execute(ddl)
        # 기존 테이블에 cca 컬럼이 없으면 추가
        cur.execute("""
            ALTER TABLE material_customer
            ADD COLUMN IF NOT EXISTS cca INT NOT NULL DEFAULT 0
            AFTER group_size
        """)
        # collation 통일 (forecast_planner 와 JOIN 시 충돌 방지)
        cur.execute("""
            ALTER TABLE material_customer
            CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
    conn.commit()


def fetch_all(conn) -> pd.DataFrame:
    cols = ["id"] + DATA_COLS + ["created_at"]
    sql = f"SELECT {', '.join(cols)} FROM material_customer ORDER BY material_code, id"
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


def insert_row(conn, row: dict) -> int:
    col_list = ", ".join(DATA_COLS)
    val_list = ", ".join(f"%({c})s" for c in DATA_COLS)
    sql = f"INSERT INTO material_customer ({col_list}) VALUES ({val_list})"
    with conn.cursor() as cur:
        cur.execute(sql, row)
        new_id = cur.lastrowid
    conn.commit()
    return int(new_id) if new_id else 0


def update_row(conn, row: dict) -> None:
    set_clause = ", ".join(f"{c} = %({c})s" for c in DATA_COLS)
    sql = f"UPDATE material_customer SET {set_clause} WHERE id = %(id)s"
    with conn.cursor() as cur:
        n = cur.execute(sql, row)
    conn.commit()
    if n == 0:
        raise ValueError("No row found for this ID.")


def delete_row(conn, row_id: int) -> None:
    with conn.cursor() as cur:
        n = cur.execute("DELETE FROM material_customer WHERE id = %s", (row_id,))
    conn.commit()
    if n == 0:
        raise ValueError("No row found to delete.")


# ── Page load ──────────────────────────────────────────────────────────────────

st.markdown("""
<div class="mc-hero">
  <h1>🔩 Material &amp; Customer</h1>
  <p>ES_USER · material_customer — material code &amp; customer master data (Oracle ESLPPROD lookup).</p>
</div>
""", unsafe_allow_html=True)

# Load reference lists from Oracle (cached)
mat_list  = fetch_oracle_materials()
cust_list, code_list, name_to_code, code_to_name = fetch_oracle_customers()

# Load MariaDB data
try:
    with db_connection() as conn:
        ensure_table(conn)
        df = fetch_all(conn)
except Exception as e:
    st.error(f"MariaDB connection failed: {e}")
    st.stop()

# ── KPI ────────────────────────────────────────────────────────────────────────

n_rows      = len(df)
n_materials = int(df["material_code"].nunique()) if n_rows else 0
n_customers = int(df["customer"].nunique()) if n_rows else 0
n_segments  = int(df["segment"].nunique()) if n_rows else 0

for col_w, (lbl, val) in zip(
    st.columns(4),
    [("Total Rows", f"{n_rows:,}"), ("Material Codes", f"{n_materials:,}"),
     ("Customers", f"{n_customers:,}"), ("Segments", f"{n_segments:,}")],
):
    with col_w:
        st.markdown(
            f'<div class="mc-card"><div class="lbl">{lbl}</div>'
            f'<div class="val">{val}</div></div>',
            unsafe_allow_html=True,
        )

st.markdown("<br>", unsafe_allow_html=True)

# ── Session state for insert key (clear-after-save) ───────────────────────────
if "mc_ins_key" not in st.session_state:
    st.session_state["mc_ins_key"] = 0
_k = st.session_state["mc_ins_key"]   # bump after each successful insert

# column order & ratios (Edit 탭 인라인 행용)
_COLS = ["material_code", "part_number", "segment", "channel",
         "customer", "customer_code", "category", "product", "group_size", "cca"]
_RATIO = [1.1, 0.75, 0.7, 0.7, 1.1, 0.8, 0.8, 0.8, 0.65, 0.6, 1.2]

# ── Row 1 ratios: Material Code | Part Number | Segment | Channel
_ROW1_RATIO = [1.3, 0.9, 0.9, 0.9]
# ── Row 2 ratios: Customer | Customer Code | Category | Product | Group Size | CCA | Save
_ROW2_RATIO = [1.4, 0.9, 0.9, 0.9, 0.8, 0.6, 1.0]

# ── Tabs ───────────────────────────────────────────────────────────────────────

st.markdown('<p class="mc-section">📝 Material & Customer Entry — Add / Edit / Save</p>',
            unsafe_allow_html=True)
tab_new, tab_edit = st.tabs(["➕ Add New Record", "✏️ Edit & Save"])

# ── Add New Record (2줄 레이아웃) ───────────────────────────────────────────────
with tab_new:
    # ── Row 1: Material Code | Part Number | Segment | Channel ──────────────
    r1h = st.columns(_ROW1_RATIO)
    for col_w, lbl in zip(r1h, ["🔩 Material Code", "🔖 Part Number", "📂 Segment", "📡 Channel"]):
        with col_w:
            st.caption(lbl)

    r1 = st.columns(_ROW1_RATIO)
    with r1[0]:
        ins_mat = st.selectbox(
            "ins_mat",
            options=mat_list if mat_list else [""],
            key=f"ins_mat_{_k}",
            label_visibility="collapsed",
        )
    with r1[1]:
        ins_pn = fetch_part_number(ins_mat)
        st.text_input("ins_pn", value=ins_pn, key=f"ins_pn_{_k}_{ins_mat}",
                      label_visibility="collapsed", disabled=True)
    with r1[2]:
        ins_seg = st.text_input("ins_seg", placeholder="Segment",
                                key=f"ins_seg_{_k}", label_visibility="collapsed")
    with r1[3]:
        ins_ch = st.text_input("ins_ch", placeholder="Channel",
                               key=f"ins_ch_{_k}", label_visibility="collapsed")

    # ── Row 2: Customer | Customer Code | Category | Product | Group Size | CCA | Save
    r2h = st.columns(_ROW2_RATIO)
    for col_w, lbl in zip(r2h, ["🏢 Customer", "🔑 Customer Code", "🗂 Category",
                                  "📦 Product", "📐 Group Size", "🏷 CCA", ""]):
        with col_w:
            st.caption(lbl)

    # Customer ↔ Customer Code 양방향 연동 (on_change 콜백 방식)
    _ins_cust_key = f"ins_cust_{_k}"
    _ins_code_key = f"ins_code_{_k}"

    # 초기값 (최초 1회만 설정)
    if _ins_cust_key not in st.session_state:
        _init_name = cust_list[0] if cust_list else ""
        st.session_state[_ins_cust_key] = _init_name
    if _ins_code_key not in st.session_state:
        st.session_state[_ins_code_key] = name_to_code.get(
            st.session_state[_ins_cust_key], code_list[0] if code_list else ""
        )

    def _ins_name_changed():
        code = name_to_code.get(st.session_state[_ins_cust_key], "")
        if code in code_list:
            st.session_state[_ins_code_key] = code

    def _ins_code_changed():
        name = code_to_name.get(st.session_state[_ins_code_key], "")
        if name in cust_list:
            st.session_state[_ins_cust_key] = name

    r2 = st.columns(_ROW2_RATIO)
    with r2[0]:
        ins_cust = st.selectbox(
            "ins_cust",
            options=cust_list if cust_list else [""],
            key=_ins_cust_key,
            on_change=_ins_name_changed,
            label_visibility="collapsed",
        )
    with r2[1]:
        ins_code = st.selectbox(
            "ins_code",
            options=code_list if code_list else [""],
            key=_ins_code_key,
            on_change=_ins_code_changed,
            label_visibility="collapsed",
        )

    with r2[2]:
        ins_cat = st.text_input("ins_cat", placeholder="Category",
                                key=f"ins_cat_{_k}", label_visibility="collapsed")
    with r2[3]:
        ins_prod = st.text_input("ins_prod", placeholder="Product",
                                 key=f"ins_prod_{_k}", label_visibility="collapsed")
    with r2[4]:
        ins_gs = st.text_input("ins_gs", placeholder="Group Size",
                               key=f"ins_gs_{_k}", label_visibility="collapsed")
    with r2[5]:
        ins_cca = st.number_input("ins_cca", min_value=0, value=0, step=1,
                                  format="%d", key=f"ins_cca_{_k}",
                                  label_visibility="collapsed")
    with r2[6]:
        if st.button("💾 Save", type="primary", use_container_width=True, key="ins_save"):
            if not ins_mat:
                st.warning("Material Code is required.")
            else:
                try:
                    with db_connection() as conn:
                        new_id = insert_row(conn, {
                            "material_code": ins_mat,
                            "part_number":   ins_pn,
                            "segment":       ins_seg.strip(),
                            "channel":       ins_ch.strip(),
                            "customer":      ins_cust,
                            "customer_code": ins_code,
                            "category":      ins_cat.strip(),
                            "product":       ins_prod.strip(),
                            "group_size":    ins_gs.strip(),
                            "cca":           int(ins_cca),
                        })
                    st.success(f"Saved — id **{new_id}**.")
                    st.session_state["mc_ins_key"] += 1
                    st.rerun()
                except Exception as ex:
                    st.error(f"Save failed: {ex}")

# ── Edit & Save ────────────────────────────────────────────────────────────────
with tab_edit:
    if df.empty:
        st.info("No data yet. Add a new record first.")
    else:
        # ── 필터 패널 ─────────────────────────────────────────────────────────
        st.markdown(
            "<div style='font-size:0.82rem;font-weight:700;color:#1a4a35;"
            "margin-bottom:6px;'>🔍 Filter rows</div>",
            unsafe_allow_html=True,
        )
        ff1, ff2, ff3 = st.columns([1.2, 1.2, 1.2])
        with ff1:
            flt_mc = st.text_input("Material Code", placeholder="e.g. ANDU…",
                                   key="mc_flt_mc", label_visibility="visible")
        with ff2:
            flt_cust = st.text_input("Customer", placeholder="Type to filter…",
                                     key="mc_flt_cust", label_visibility="visible")
        with ff3:
            seg_opts = ["(All)"] + sorted(
                df["segment"].fillna("").astype(str).str.strip()
                .replace("", pd.NA).dropna().unique().tolist()
            )
            flt_seg = st.selectbox("Segment", options=seg_opts,
                                   key="mc_flt_seg", label_visibility="visible")

        # 필터 적용
        view = df.copy()
        if flt_mc.strip():
            view = view[view["material_code"].astype(str)
                        .str.contains(flt_mc.strip(), case=False, na=False)]
        if flt_cust.strip():
            view = view[view["customer"].astype(str)
                        .str.contains(flt_cust.strip(), case=False, na=False)]
        if flt_seg != "(All)":
            view = view[view["segment"].astype(str).str.strip() == flt_seg]

        view = view.sort_values(["material_code", "id"])

        st.caption(f"**{len(view):,}** row(s) match · click a row to select it for editing")

        # ── 클릭 선택 테이블 ──────────────────────────────────────────────────
        tbl_cols = ["id", "material_code", "part_number", "segment", "channel",
                    "customer", "customer_code", "category", "product", "group_size", "cca"]
        tbl_cols = [c for c in tbl_cols if c in view.columns]

        event = st.dataframe(
            view[tbl_cols].reset_index(drop=True),
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "id":            st.column_config.NumberColumn("ID", format="%d"),
                "material_code": st.column_config.TextColumn("Material Code"),
                "part_number":   st.column_config.TextColumn("Part Number"),
                "segment":       st.column_config.TextColumn("Segment"),
                "channel":       st.column_config.TextColumn("Channel"),
                "customer":      st.column_config.TextColumn("Customer"),
                "customer_code": st.column_config.TextColumn("Customer Code"),
                "category":      st.column_config.TextColumn("Category"),
                "product":       st.column_config.TextColumn("Product"),
                "group_size":    st.column_config.TextColumn("Group Size"),
                "cca":           st.column_config.NumberColumn("CCA", format="%d"),
            },
            key="mc_edit_table",
        )

        selected_rows = (
            event.selection.get("rows", [])
            if event and hasattr(event, "selection") else []
        )
        pick = None
        if selected_rows:
            sel_idx = selected_rows[0]
            sel_view = view[tbl_cols].reset_index(drop=True)
            if sel_idx < len(sel_view):
                pick = int(sel_view.iloc[sel_idx]["id"])

        if pick is None:
            st.info("👆 Click a row above to load it into the edit form.")
        else:
            rec = df.loc[df["id"] == pick].iloc[0]

            def _sv(col: str) -> str:
                v = rec.get(col, "")
                return str(v) if pd.notna(v) else ""

            st.markdown(
                f"<div style='background:#e6f4ec;border-left:4px solid #2d7a55;"
                f"border-radius:8px;padding:8px 14px;margin:10px 0 6px;"
                f"font-size:0.88rem;color:#1a4a35;font-weight:600;'>"
                f"✏️ Editing ID <b>#{pick}</b> — {_sv('material_code')} "
                f"/ {_sv('customer')}</div>",
                unsafe_allow_html=True,
            )
            st.caption("Edit values then **Save**, or **Delete** to remove (cannot be undone).")

            p = pick

            # ── Row 1: Material Code | Part Number | Segment | Channel ───────
            er1h = st.columns(_ROW1_RATIO)
            for col_w, lbl in zip(er1h, ["🔩 Material Code", "🔖 Part Number", "📂 Segment", "📡 Channel"]):
                with col_w:
                    st.caption(lbl)

            er1 = st.columns(_ROW1_RATIO)
            with er1[0]:
                _cur_mat = _sv("material_code")
                _mat_idx = mat_list.index(_cur_mat) if _cur_mat in mat_list else 0
                edit_mat = st.selectbox(
                    "edit_mat",
                    options=mat_list if mat_list else [_cur_mat],
                    index=_mat_idx,
                    key=f"edit_mat_{p}",
                    label_visibility="collapsed",
                )
            with er1[1]:
                edit_pn = fetch_part_number(edit_mat)
                st.text_input("edit_pn", value=edit_pn, key=f"edit_pn_{p}_{edit_mat}",
                              label_visibility="collapsed", disabled=True)
            with er1[2]:
                edit_seg = st.text_input("edit_seg", value=_sv("segment"),
                                         key=f"edit_seg_{p}", label_visibility="collapsed",
                                         placeholder="Segment")
            with er1[3]:
                edit_ch = st.text_input("edit_ch", value=_sv("channel"),
                                        key=f"edit_ch_{p}", label_visibility="collapsed",
                                        placeholder="Channel")

            # ── Row 2: Customer | Customer Code | Category | Product | Group Size | CCA | Save | Del
            er2h = st.columns(_ROW2_RATIO)
            for col_w, lbl in zip(er2h, ["🏢 Customer", "🔑 Customer Code", "🗂 Category",
                                          "📦 Product", "📐 Group Size", "🏷 CCA", ""]):
                with col_w:
                    st.caption(lbl)

            # Customer ↔ Customer Code 양방향 연동 (Edit 탭, on_change 콜백 방식)
            _ec_name_key = f"edit_cust_{p}"
            _ec_code_key = f"edit_code_{p}"

            _cur_cust = _sv("customer")
            _cur_code = _sv("customer_code")
            # 레코드 선택 시 p가 바뀌므로 키가 새로 생성되어 초기값으로 채워짐
            if _ec_name_key not in st.session_state:
                st.session_state[_ec_name_key] = _cur_cust if _cur_cust in cust_list else (cust_list[0] if cust_list else "")
            if _ec_code_key not in st.session_state:
                st.session_state[_ec_code_key] = _cur_code if _cur_code in code_list else (code_list[0] if code_list else "")

            def _edit_name_changed():
                code = name_to_code.get(st.session_state[_ec_name_key], "")
                if code in code_list:
                    st.session_state[_ec_code_key] = code

            def _edit_code_changed():
                name = code_to_name.get(st.session_state[_ec_code_key], "")
                if name in cust_list:
                    st.session_state[_ec_name_key] = name

            er2 = st.columns(_ROW2_RATIO)
            with er2[0]:
                edit_cust = st.selectbox(
                    "edit_cust",
                    options=cust_list if cust_list else [_cur_cust],
                    key=_ec_name_key,
                    on_change=_edit_name_changed,
                    label_visibility="collapsed",
                )
            with er2[1]:
                edit_code = st.selectbox(
                    "edit_code",
                    options=code_list if code_list else [_cur_code],
                    key=_ec_code_key,
                    on_change=_edit_code_changed,
                    label_visibility="collapsed",
                )
            with er2[2]:
                edit_cat = st.text_input("edit_cat", value=_sv("category"),
                                         key=f"edit_cat_{p}", label_visibility="collapsed",
                                         placeholder="Category")
            with er2[3]:
                edit_prod = st.text_input("edit_prod", value=_sv("product"),
                                          key=f"edit_prod_{p}", label_visibility="collapsed",
                                          placeholder="Product")
            with er2[4]:
                edit_gs = st.text_input("edit_gs", value=_sv("group_size"),
                                        key=f"edit_gs_{p}", label_visibility="collapsed",
                                        placeholder="Group Size")
            with er2[5]:
                _cur_cca = rec.get("cca", 0)
                try:
                    _cur_cca = int(_cur_cca) if pd.notna(_cur_cca) else 0
                except (ValueError, TypeError):
                    _cur_cca = 0
                edit_cca = st.number_input("edit_cca", min_value=0, value=_cur_cca,
                                           step=1, format="%d", key=f"edit_cca_{p}",
                                           label_visibility="collapsed")
            with er2[6]:
                bl, br = st.columns(2, gap="small")
                with bl:
                    save_btn = st.button("💾 Save", type="primary",
                                         use_container_width=True, key=f"edit_save_{p}")
                with br:
                    del_btn = st.button("🗑 Del", type="secondary",
                                        use_container_width=True, key=f"edit_del_{p}")

            if del_btn:
                try:
                    with db_connection() as conn:
                        delete_row(conn, int(pick))
                    st.success(f"ID {pick} deleted.")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Delete failed: {ex}")
            elif save_btn:
                try:
                    with db_connection() as conn:
                        update_row(conn, {
                            "id":            int(pick),
                            "material_code": edit_mat,
                            "part_number":   edit_pn,
                            "segment":       edit_seg.strip(),
                            "channel":       edit_ch.strip(),
                            "customer":      edit_cust,
                            "customer_code": edit_code,
                            "category":      edit_cat.strip(),
                            "product":       edit_prod.strip(),
                            "group_size":    edit_gs.strip(),
                            "cca":           int(edit_cca),
                        })
                    st.success(f"ID {pick} saved.")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Save failed: {ex}")

# ── Full list ──────────────────────────────────────────────────────────────────

st.markdown('<p class="mc-section">📋 Master Status : Material - Customer</p>', unsafe_allow_html=True)

if df.empty:
    st.info("No records yet.")
else:
    disp_search = st.text_input("🔍 Filter list", key="mc_disp_search",
                                placeholder="Material code or customer…")
    df_show = df.copy()
    if disp_search.strip():
        mask = (
            df_show["material_code"].str.contains(disp_search.strip(), case=False, na=False) |
            df_show["customer"].str.contains(disp_search.strip(), case=False, na=False)
        )
        df_show = df_show.loc[mask]

    st.dataframe(
        df_show[DATA_COLS],
        use_container_width=True,
        hide_index=True,
        column_config={
            "material_code": st.column_config.TextColumn("Material Code"),
            "segment":       st.column_config.TextColumn("Segment"),
            "channel":       st.column_config.TextColumn("Channel"),
            "customer":      st.column_config.TextColumn("Customer"),
            "customer_code": st.column_config.TextColumn("Customer Code"),
            "category":      st.column_config.TextColumn("Category"),
            "product":       st.column_config.TextColumn("Product"),
            "group_size":    st.column_config.TextColumn("Group Size"),
            "cca":           st.column_config.NumberColumn("CCA", format="%d"),
            "part_number":   st.column_config.TextColumn("Part Number"),
        },
    )
    st.caption(f"{len(df_show):,} row(s) displayed / {n_rows:,} total")

st.markdown("---")
st.caption(
    f"MariaDB: **ES_USER.material_customer** · Oracle: **ESLPPROD** · "
    f"configs: `{MARIA_CFG.name}`, `{ORACLE_CFG.name}`"
)
st.markdown(
    "<div style='text-align:center;color:#aaa;font-size:.78rem;padding:10px;'>"
    "© 2026 Hankook &amp; Company ES America Corp. &nbsp;|&nbsp; Master: Material &amp; Customer"
    "</div>",
    unsafe_allow_html=True,
)
