"""
Forecast Planner — ES_USER.forecast_planner CRUD (MariaDB)
Connection settings: info_config/mariadb_es_user.json

Forecast columns (qty replaced):
  Cur_Wk_Customer_Frcst     INT
  Cur_Wk_Statistical_Frcst  INT
  90_Day_Customer_Frcst     INT
  90_Day_Statistical_Frcst  INT

forecast_month (VARCHAR 7, e.g. '2026-05') is auto-derived from forecast_date on insert/update.
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import pymysql
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "info_config" / "mariadb_es_user.json"

sys.path.insert(0, str(BASE_DIR))
from utils.access_logger import log_access

# 4개 예측 컬럼 정의 (순서 유지)
FRCST_COLS = [
    "Cur_Wk_Customer_Frcst",
    "Cur_Wk_Statistical_Frcst",
    "90_Day_Customer_Frcst",
    "90_Day_Statistical_Frcst",
]
FRCST_LABELS = {
    "Cur_Wk_Customer_Frcst":    "CW Customer",
    "Cur_Wk_Statistical_Frcst": "CW Statistical",
    "90_Day_Customer_Frcst":    "90D Customer",
    "90_Day_Statistical_Frcst": "90D Statistical",
}
ALL_COLS = [
    "id", "forecast_date", "forecast_month", "replenishment_date",
    "sales_person", "forecast_material_code",
] + FRCST_COLS

st.set_page_config(
    page_title="Forecast Planner",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded",
)
log_access("Forecast Planner")

st.markdown(
    """
<style>
    .main { background: linear-gradient(180deg, #e8eef5 0%, #f4f6fa 45%, #f0f2f6 100%); }
    .block-container { padding-top: 1.2rem; padding-bottom: 2.5rem; }

    .fp-hero {
        background: linear-gradient(135deg, #1e3a5f 0%, #2d5a87 40%, #3d7ab0 100%);
        color: #fff; border-radius: 16px; padding: 1.25rem 1.75rem;
        margin-bottom: 1.25rem; box-shadow: 0 10px 40px rgba(30,58,95,0.35);
    }
    .fp-hero h1 { margin:0; font-size:1.75rem; font-weight:800; letter-spacing:-0.02em; }
    .fp-hero p  { margin:0.5rem 0 0; opacity:0.92; font-size:0.95rem; }

    .fp-card {
        background:#fff; border-radius:12px; padding:14px 18px;
        box-shadow:0 4px 18px rgba(0,0,0,0.07);
        border-left:4px solid #2d5a87; text-align:center;
    }
    .fp-card .lbl {
        font-size:0.72rem; text-transform:uppercase;
        letter-spacing:0.08em; color:#889; font-weight:700;
    }
    .fp-card .val { font-size:1.45rem; font-weight:800; color:#1a1a2e; margin-top:4px; }

    .fp-section {
        font-size:1.05rem; font-weight:700; color:#1e3a5f;
        margin:1.1rem 0 0.6rem; padding-bottom:6px;
        border-bottom:2px solid #c5d4e8;
    }
    div[data-testid="stTabs"] button { font-weight:600; }
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
    conn = pymysql.connect(
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


def ensure_table(conn) -> None:
    """테이블이 없으면 새 스키마로 생성, 있으면 migrate_table 로 컬럼 동기화."""
    ddl = """
    CREATE TABLE IF NOT EXISTS forecast_planner (
        id                       INT UNSIGNED  NOT NULL AUTO_INCREMENT PRIMARY KEY,
        forecast_date            DATE          NOT NULL,
        forecast_month           VARCHAR(7)    NOT NULL DEFAULT '',
        replenishment_date       DATE          NOT NULL,
        sales_person             VARCHAR(200)  NOT NULL DEFAULT '',
        forecast_material_code   VARCHAR(120)  NOT NULL DEFAULT '',
        Cur_Wk_Customer_Frcst    INT           NOT NULL DEFAULT 0,
        Cur_Wk_Statistical_Frcst INT           NOT NULL DEFAULT 0,
        `90_Day_Customer_Frcst`  INT           NOT NULL DEFAULT 0,
        `90_Day_Statistical_Frcst` INT         NOT NULL DEFAULT 0,
        KEY idx_forecast_date (forecast_date),
        KEY idx_material (forecast_material_code)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """
    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()
    migrate_table(conn)


def migrate_table(conn) -> None:
    """기존 테이블에 신규 컬럼 추가 & qty 컬럼 제거."""
    add_stmts = [
        "ALTER TABLE forecast_planner ADD COLUMN IF NOT EXISTS "
        "forecast_month VARCHAR(7) NOT NULL DEFAULT '' AFTER forecast_date",
        "ALTER TABLE forecast_planner ADD COLUMN IF NOT EXISTS "
        "Cur_Wk_Customer_Frcst INT NOT NULL DEFAULT 0",
        "ALTER TABLE forecast_planner ADD COLUMN IF NOT EXISTS "
        "Cur_Wk_Statistical_Frcst INT NOT NULL DEFAULT 0",
        "ALTER TABLE forecast_planner ADD COLUMN IF NOT EXISTS "
        "`90_Day_Customer_Frcst` INT NOT NULL DEFAULT 0",
        "ALTER TABLE forecast_planner ADD COLUMN IF NOT EXISTS "
        "`90_Day_Statistical_Frcst` INT NOT NULL DEFAULT 0",
    ]
    # qty 컬럼 존재 여부 확인 후 제거
    check_qty = """
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = 'forecast_planner'
          AND COLUMN_NAME  = 'qty'
    """
    with conn.cursor() as cur:
        for stmt in add_stmts:
            try:
                cur.execute(stmt)
            except Exception:
                pass
        cur.execute(check_qty)
        row = cur.fetchone()
        if row and int(row[0]) > 0:
            try:
                cur.execute("ALTER TABLE forecast_planner DROP COLUMN qty")
            except Exception:
                pass
    conn.commit()


def fetch_active_sales_persons(conn) -> list[str]:
    sql = "SELECT name FROM sales_person WHERE active=1 ORDER BY name ASC"
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            return [r[0] for r in cur.fetchall()]
    except Exception:
        return []


def fetch_all_planner(conn) -> pd.DataFrame:
    col_list = ", ".join(
        f"`{c}`" if c.startswith("9") else c for c in ALL_COLS
    )
    sql = f"""
    SELECT {col_list}
    FROM forecast_planner
    ORDER BY forecast_date DESC, id DESC
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=ALL_COLS)
    return pd.DataFrame(rows, columns=ALL_COLS)


# material_customer 와 LEFT JOIN 한 결과용 컬럼
MC_JOIN_COLS = ["mc_segment", "mc_channel", "mc_customer",
                "mc_category", "mc_product", "mc_group_size", "mc_part_number"]

def fetch_all_planner_joined(conn) -> pd.DataFrame:
    """forecast_planner LEFT JOIN material_customer ON forecast_material_code = material_code."""
    fp_cols = ", ".join(
        f"fp.`{c}`" if c.startswith("9") else f"fp.{c}" for c in ALL_COLS
    )
    sql = f"""
    SELECT
        {fp_cols},
        mc.segment    AS mc_segment,
        mc.channel    AS mc_channel,
        mc.customer   AS mc_customer,
        mc.category   AS mc_category,
        mc.product    AS mc_product,
        mc.group_size AS mc_group_size,
        mc.part_number AS mc_part_number
    FROM forecast_planner fp
    LEFT JOIN material_customer mc
           ON fp.forecast_material_code COLLATE utf8mb4_unicode_ci
            = mc.material_code         COLLATE utf8mb4_unicode_ci
    ORDER BY fp.forecast_date DESC, fp.id DESC
    """
    all_cols = ALL_COLS + MC_JOIN_COLS
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=all_cols)
    return pd.DataFrame(rows, columns=all_cols)


def insert_row(conn, row: dict) -> int:
    sql = """
    INSERT INTO forecast_planner (
        forecast_date, forecast_month, replenishment_date, sales_person,
        forecast_material_code,
        Cur_Wk_Customer_Frcst, Cur_Wk_Statistical_Frcst,
        `90_Day_Customer_Frcst`, `90_Day_Statistical_Frcst`
    ) VALUES (
        %(forecast_date)s, %(forecast_month)s, %(replenishment_date)s, %(sales_person)s,
        %(forecast_material_code)s,
        %(Cur_Wk_Customer_Frcst)s, %(Cur_Wk_Statistical_Frcst)s,
        %(90_Day_Customer_Frcst)s, %(90_Day_Statistical_Frcst)s
    )
    """
    with conn.cursor() as cur:
        cur.execute(sql, row)
        new_id = cur.lastrowid
    conn.commit()
    return int(new_id) if new_id else 0


def update_row(conn, row: dict) -> None:
    sql = """
    UPDATE forecast_planner SET
        forecast_date            = %(forecast_date)s,
        forecast_month           = %(forecast_month)s,
        replenishment_date       = %(replenishment_date)s,
        sales_person             = %(sales_person)s,
        forecast_material_code   = %(forecast_material_code)s,
        Cur_Wk_Customer_Frcst    = %(Cur_Wk_Customer_Frcst)s,
        Cur_Wk_Statistical_Frcst = %(Cur_Wk_Statistical_Frcst)s,
        `90_Day_Customer_Frcst`  = %(90_Day_Customer_Frcst)s,
        `90_Day_Statistical_Frcst` = %(90_Day_Statistical_Frcst)s
    WHERE id = %(id)s
    """
    with conn.cursor() as cur:
        n = cur.execute(sql, row)
    conn.commit()
    if n == 0:
        raise ValueError("No row exists for this ID.")


def delete_row(conn, row_id: int) -> None:
    with conn.cursor() as cur:
        n = cur.execute("DELETE FROM forecast_planner WHERE id=%s", (row_id,))
    conn.commit()
    if n == 0:
        raise ValueError("No row found to delete.")


def delete_junk_header_rows(conn) -> int:
    patterns = [
        """DELETE FROM forecast_planner
           WHERE LOWER(TRIM(sales_person)) = 'sales_person'
             AND LOWER(TRIM(forecast_material_code)) = 'forecast_material_code'""",
        """DELETE FROM forecast_planner
           WHERE LOWER(TRIM(CAST(id AS CHAR))) = 'id'""",
        """DELETE FROM forecast_planner
           WHERE id = 0
             AND LOWER(TRIM(sales_person)) = 'sales_person'""",
    ]
    total = 0
    with conn.cursor() as cur:
        for sql in patterns:
            cur.execute(sql)
            total += int(cur.rowcount or 0)
    conn.commit()
    return total


def _sql_param_for_cell(v) -> str | None:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def delete_corrupt_rows_exact(conn, corrupt: pd.DataFrame) -> int:
    if corrupt.empty:
        return 0
    check_cols = ["id", "forecast_date", "replenishment_date",
                  "sales_person", "forecast_material_code"]
    total = 0
    seen: set[tuple] = set()
    with conn.cursor() as cur:
        for _, row in corrupt.iterrows():
            parts, params = [], []
            for c in check_cols:
                if c not in row.index:
                    continue
                p = _sql_param_for_cell(row[c])
                if p is None:
                    parts.append(f"`{c}` IS NULL")
                else:
                    parts.append(f"LOWER(TRIM(CAST(`{c}` AS CHAR)))=LOWER(%s)")
                    params.append(p)
            sql = "DELETE FROM forecast_planner WHERE " + " AND ".join(parts)
            key = (sql, tuple(params))
            if key in seen:
                continue
            seen.add(key)
            cur.execute(sql, params)
            total += int(cur.rowcount or 0)
    conn.commit()
    return total


def purge_junk_rows(conn, corrupt: pd.DataFrame | None) -> int:
    n = delete_junk_header_rows(conn)
    if corrupt is not None and not corrupt.empty:
        n += delete_corrupt_rows_exact(conn, corrupt)
    return n


def safe_int_input(value) -> int:
    x = pd.to_numeric(value, errors="coerce")
    return 0 if pd.isna(x) else int(round(float(x)))


def to_int_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").round().astype("Int64")


def prepare_planner_df(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if data.empty or "id" not in data.columns:
        return data, pd.DataFrame()
    id_num = pd.to_numeric(data["id"], errors="coerce")
    bad = id_num.isna()
    corrupt = data.loc[bad].copy()
    good = data.loc[~bad].copy()
    if good.empty:
        return pd.DataFrame(columns=data.columns), corrupt
    good = good.copy()
    good["id"] = id_num[~bad].astype(int)
    return good, corrupt


def _format_id_cell(value) -> str:
    x = pd.to_numeric(value, errors="coerce")
    return str(int(x)) if pd.notna(x) else str(value)


def _row_label(r: pd.Series) -> str:
    cw = safe_int_input(r.get("Cur_Wk_Customer_Frcst", 0))
    d90 = safe_int_input(r.get("90_Day_Customer_Frcst", 0))
    return (
        f"#{_format_id_cell(r['id'])} | {r['forecast_date']} | "
        f"{r['forecast_material_code']} | CW:{cw:,}  90D:{d90:,}"
    )


# ── Page load ─────────────────────────────────────────────────────────────────

st.markdown(
    """
    <div class="fp-hero">
      <h1>📅 Forecast Planner</h1>
      <p>ES_USER · forecast_planner — manage forecast quantities by current week and 90-day horizons.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

try:
    with db_connection() as conn:
        ensure_table(conn)
        df_raw = fetch_all_planner(conn)
        df_joined = fetch_all_planner_joined(conn)
        sp_list = fetch_active_sales_persons(conn)
except Exception as e:
    st.error(f"Database connection or initialization failed: {e}")
    st.info("Check `info_config/mariadb_es_user.json` and retry.")
    st.stop()

if not sp_list and not df_raw.empty:
    existing = df_raw["sales_person"].fillna("").astype(str).str.strip()
    sp_list = sorted({v for v in existing if v})

df, df_corrupt = prepare_planner_df(df_raw)

if not df_corrupt.empty:
    st.error("**Rows with non-numeric `id`** detected. They are hidden from the list below.")
    st.dataframe(df_corrupt, use_container_width=True)
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Delete junk / header rows in DB", type="primary", key="fp_del_junk_main"):
            try:
                with db_connection() as conn:
                    n = purge_junk_rows(conn, df_corrupt)
                st.success(f"Removed {n} row(s). Refreshing.")
                st.rerun()
            except Exception as e:
                st.error(f"Cleanup failed: {e}")
    with b2:
        st.caption("Click the button on the left to remove junk rows and refresh.")

# ── KPI ────────────────────────────────────────────────────────────────────────

n_rows = len(df)
n_materials = int(df["forecast_material_code"].nunique()) if n_rows else 0
_sp = df["sales_person"].fillna("").astype(str).str.strip()
n_staff = int(_sp[_sp != ""].nunique()) if n_rows else 0

def _col_sum(col: str) -> int:
    if not n_rows or col not in df.columns:
        return 0
    return int(to_int_series(df[col]).sum())

k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
for col_w, (lbl, val) in zip(
    [k1, k2, k3, k4, k5, k6, k7],
    [
        ("Count",            f"{n_rows:,}"),
        ("Material Codes",  f"{n_materials:,}"),
        ("Sales Owners",    f"{n_staff:,}"),
        ("CW Customer",     f"{_col_sum('Cur_Wk_Customer_Frcst'):,}"),
        ("CW Statistical",  f"{_col_sum('Cur_Wk_Statistical_Frcst'):,}"),
        ("90D Customer",    f"{_col_sum('90_Day_Customer_Frcst'):,}"),
        ("90D Statistical", f"{_col_sum('90_Day_Statistical_Frcst'):,}"),
    ],
):
    with col_w:
        st.markdown(
            f'<div class="fp-card"><div class="lbl">{lbl}</div>'
            f'<div class="val">{val}</div></div>',
            unsafe_allow_html=True,
        )

st.markdown("<br>", unsafe_allow_html=True)

st.markdown('<p class="fp-section">📝 Forecast Plan Entry — Add / Edit / Save</p>', unsafe_allow_html=True)
tab_new, tab_edit = st.tabs(["➕ Add New Record", "✏️ Edit & Save"])

# column layout: date | replen | sales | material | CW Cust | CW Stat | 90D Cust | 90D Stat | save
_HDR = [
    "📅 Forecast Date", "🚚 Replenish Date",
    "👤 Sales Person", "🔩 Material Code",
    "CW Customer", "CW Statistical",
    "90D Customer", "90D Statistical",
    "",
]
_RATIO = [0.7, 0.7, 1.0, 1.0, 0.75, 0.75, 0.75, 0.75, 1.3]

with tab_new:
    with st.form("fp_insert", clear_on_submit=True):
        # header row
        for hcol, htxt in zip(st.columns(_RATIO), _HDR):
            with hcol:
                st.caption(htxt)
        # input row
        ic = st.columns(_RATIO)
        with ic[0]:
            f_date = st.date_input("fd", value=date.today(),
                                   key="ins_fd", label_visibility="collapsed")
        with ic[1]:
            r_date = st.date_input("rd", value=date.today(),
                                   key="ins_rd", label_visibility="collapsed")
        with ic[2]:
            _sp_opts = sp_list if sp_list else ["(none)"]
            sp = st.selectbox("sp", options=_sp_opts,
                              key="ins_sp", label_visibility="collapsed")
        with ic[3]:
            mc = st.text_input("mc", placeholder="Material code",
                               key="ins_mc", label_visibility="collapsed")
        with ic[4]:
            cw_cust = st.number_input("cwc", min_value=0, value=0, step=1,
                                      format="%d", key="ins_cwc",
                                      label_visibility="collapsed")
        with ic[5]:
            cw_stat = st.number_input("cws", min_value=0, value=0, step=1,
                                      format="%d", key="ins_cws",
                                      label_visibility="collapsed")
        with ic[6]:
            d90_cust = st.number_input("d9c", min_value=0, value=0, step=1,
                                       format="%d", key="ins_d9c",
                                       label_visibility="collapsed")
        with ic[7]:
            d90_stat = st.number_input("d9s", min_value=0, value=0, step=1,
                                       format="%d", key="ins_d9s",
                                       label_visibility="collapsed")
        with ic[8]:
            submitted = st.form_submit_button("💾 Save", type="primary",
                                              use_container_width=True)
        if submitted:
            try:
                with db_connection() as conn:
                    new_id = insert_row(conn, {
                        "forecast_date":  f_date,
                        "forecast_month": f_date.strftime("%Y-%m"),
                        "replenishment_date": r_date,
                        "sales_person": "" if sp == "(none)" else sp,
                        "forecast_material_code": mc.strip().upper(),
                        "Cur_Wk_Customer_Frcst":    int(cw_cust),
                        "Cur_Wk_Statistical_Frcst": int(cw_stat),
                        "90_Day_Customer_Frcst":    int(d90_cust),
                        "90_Day_Statistical_Frcst": int(d90_stat),
                    })
                st.success(f"Saved — id **{new_id}**.")
                st.rerun()
            except Exception as ex:
                st.error(f"Save failed: {ex}")

with tab_edit:
    if df.empty:
        st.info("No data to edit. Add a new record first.")
    else:
        # ── 필터 패널 ─────────────────────────────────────────────────────────
        st.markdown(
            "<div style='font-size:0.82rem;font-weight:700;color:#1e3a5f;"
            "margin-bottom:6px;'>🔍 Filter rows</div>",
            unsafe_allow_html=True,
        )
        fc1, fc2, fc3 = st.columns([1.2, 1.2, 1.6])
        with fc1:
            flt_mc = st.text_input("Material code", placeholder="e.g. ANDU…",
                                   key="flt_mc", label_visibility="visible")
        with fc2:
            sp_opts_flt = ["(All)"] + (sp_list if sp_list else
                sorted(df["sales_person"].fillna("").astype(str).str.strip().unique().tolist()))
            flt_sp = st.selectbox("Sales person", options=sp_opts_flt,
                                  key="flt_sp", label_visibility="visible")
        with fc3:
            _dates = pd.to_datetime(df["forecast_date"], errors="coerce").dropna()
            _min_d = _dates.min().date() if len(_dates) else date.today()
            _max_d = _dates.max().date() if len(_dates) else date.today()
            flt_date = st.date_input(
                "Forecast date range",
                value=(_min_d, _max_d),
                min_value=_min_d, max_value=_max_d,
                key="flt_date", label_visibility="visible",
            )

        # 필터 적용
        view = df.copy()
        view["forecast_date"] = pd.to_datetime(view["forecast_date"], errors="coerce")
        if flt_mc.strip():
            view = view[view["forecast_material_code"].astype(str)
                        .str.contains(flt_mc.strip(), case=False, na=False)]
        if flt_sp != "(All)":
            view = view[view["sales_person"].astype(str).str.strip() == flt_sp]
        if isinstance(flt_date, (list, tuple)) and len(flt_date) == 2:
            d_from, d_to = pd.Timestamp(flt_date[0]), pd.Timestamp(flt_date[1])
            view = view[(view["forecast_date"] >= d_from) & (view["forecast_date"] <= d_to)]

        view = view.sort_values("forecast_date", ascending=False)
        view["forecast_date"] = view["forecast_date"].dt.date

        st.caption(f"**{len(view):,}** row(s) match · click a row to select it for editing")

        # ── 클릭 선택 테이블 ──────────────────────────────────────────────────
        sel_cols = ["id", "forecast_date", "replenishment_date",
                    "sales_person", "forecast_material_code"] + FRCST_COLS
        sel_cols = [c for c in sel_cols if c in view.columns]

        event = st.dataframe(
            view[sel_cols].reset_index(drop=True),
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "id":                      st.column_config.NumberColumn("ID", format="%d"),
                "forecast_date":           st.column_config.DateColumn("Forecast Date"),
                "replenishment_date":      st.column_config.DateColumn("Replenish Date"),
                "sales_person":            st.column_config.TextColumn("Sales Person"),
                "forecast_material_code":  st.column_config.TextColumn("Material Code"),
                "Cur_Wk_Customer_Frcst":   st.column_config.NumberColumn("CW Customer",    format="%d"),
                "Cur_Wk_Statistical_Frcst":st.column_config.NumberColumn("CW Statistical", format="%d"),
                "90_Day_Customer_Frcst":   st.column_config.NumberColumn("90D Customer",   format="%d"),
                "90_Day_Statistical_Frcst":st.column_config.NumberColumn("90D Statistical",format="%d"),
            },
            key="edit_table",
        )

        # 선택된 행 처리
        selected_rows = event.selection.get("rows", []) if event and hasattr(event, "selection") else []
        pick = None
        if selected_rows:
            sel_idx = selected_rows[0]
            sel_view = view[sel_cols].reset_index(drop=True)
            if sel_idx < len(sel_view):
                pick = int(sel_view.iloc[sel_idx]["id"])

        if pick is None:
            st.info("👆 Click a row above to load it into the edit form.")
        else:
            rec = df.loc[df["id"] == pick].iloc[0]
            cur_f = pd.to_datetime(rec["forecast_date"]).date()
            cur_r = pd.to_datetime(rec["replenishment_date"]).date()

            st.markdown(
                f"<div style='background:#e8f0fb;border-left:4px solid #2d5a87;"
                f"border-radius:8px;padding:8px 14px;margin:10px 0 6px;"
                f"font-size:0.88rem;color:#1e3a5f;font-weight:600;'>"
                f"✏️ Editing ID <b>#{pick}</b> — {rec['forecast_material_code']} "
                f"/ {cur_f}</div>",
                unsafe_allow_html=True,
            )
            st.caption("Edit values then **Save**, or click **Delete** to remove (cannot be undone).")

            # pick이 바뀔 때마다 widget key를 달리해서 session_state 캐시를 무효화
            p = pick
            with st.form(f"fp_update_{p}"):
                for hcol, htxt in zip(st.columns(_RATIO), _HDR):
                    with hcol:
                        st.caption(htxt)
                uc = st.columns(_RATIO)
                with uc[0]:
                    uf = st.date_input("ufd", value=cur_f,
                                       key=f"up_fd_{p}", label_visibility="collapsed")
                with uc[1]:
                    ur = st.date_input("urd", value=cur_r,
                                       key=f"up_rd_{p}", label_visibility="collapsed")
                with uc[2]:
                    _sp_opts_e = sp_list if sp_list else ["(none)"]
                    _cur_sp = str(rec["sales_person"])
                    _sp_idx = _sp_opts_e.index(_cur_sp) if _cur_sp in _sp_opts_e else 0
                    usp = st.selectbox("usp", options=_sp_opts_e, index=_sp_idx,
                                       key=f"up_sp_{p}", label_visibility="collapsed")
                with uc[3]:
                    umc = st.text_input("umc", value=str(rec["forecast_material_code"]),
                                        placeholder="Material code",
                                        key=f"up_mc_{p}", label_visibility="collapsed")
                with uc[4]:
                    ucw_cust = st.number_input("ucwc",
                        value=safe_int_input(rec.get("Cur_Wk_Customer_Frcst", 0)),
                        min_value=0, step=1, format="%d",
                        key=f"up_cwc_{p}", label_visibility="collapsed")
                with uc[5]:
                    ucw_stat = st.number_input("ucws",
                        value=safe_int_input(rec.get("Cur_Wk_Statistical_Frcst", 0)),
                        min_value=0, step=1, format="%d",
                        key=f"up_cws_{p}", label_visibility="collapsed")
                with uc[6]:
                    ud90_cust = st.number_input("ud9c",
                        value=safe_int_input(rec.get("90_Day_Customer_Frcst", 0)),
                        min_value=0, step=1, format="%d",
                        key=f"up_d9c_{p}", label_visibility="collapsed")
                with uc[7]:
                    ud90_stat = st.number_input("ud9s",
                        value=safe_int_input(rec.get("90_Day_Statistical_Frcst", 0)),
                        min_value=0, step=1, format="%d",
                        key=f"up_d9s_{p}", label_visibility="collapsed")
                with uc[8]:
                    bl, br = st.columns(2, gap="small")
                    with bl:
                        save = st.form_submit_button("💾 Save", type="primary",
                                                     use_container_width=True)
                    with br:
                        delete_btn = st.form_submit_button("🗑 Del", type="secondary",
                                                           use_container_width=True)

            if delete_btn:
                try:
                    with db_connection() as conn:
                        delete_row(conn, int(pick))
                    st.success(f"ID {pick} deleted.")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Delete failed: {ex}")
            elif save:
                try:
                    with db_connection() as conn:
                        update_row(conn, {
                            "id": int(pick),
                            "forecast_date":  uf,
                            "forecast_month": uf.strftime("%Y-%m"),
                            "replenishment_date": ur,
                            "sales_person": "" if usp == "(none)" else usp,
                            "forecast_material_code": umc.strip().upper(),
                            "Cur_Wk_Customer_Frcst":    int(ucw_cust),
                            "Cur_Wk_Statistical_Frcst": int(ucw_stat),
                            "90_Day_Customer_Frcst":    int(ud90_cust),
                            "90_Day_Statistical_Frcst": int(ud90_stat),
                        })
                    st.success(f"ID {pick} saved.")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Save failed: {ex}")
# ── Full list ──────────────────────────────────────────────────────────────────

st.markdown('<p class="fp-section">📋 Forecast Planner</p>', unsafe_allow_html=True)
if df.empty:
    st.write("No valid rows to display.")
    if not df_raw.empty:
        st.warning(
            f"MariaDB returns **{len(df_raw)}** row(s) but all have invalid `id`. "
            "Use **Delete junk / header rows in DB** above."
        )
else:
    show = df_joined.copy()
    show["forecast_date"] = pd.to_datetime(show["forecast_date"]).dt.date
    show["replenishment_date"] = pd.to_datetime(show["replenishment_date"]).dt.date
    for c in FRCST_COLS:
        if c in show.columns:
            show[c] = to_int_series(show[c])

    # id·joined-id 제외, Material Code 첫 번째
    display_cols = [
        "forecast_material_code",
        "forecast_date", "forecast_month", "replenishment_date",
        "sales_person",
    ] + FRCST_COLS + [
        "mc_segment", "mc_channel", "mc_customer",
        "mc_category", "mc_product", "mc_group_size", "mc_part_number",
    ]
    display_cols = [c for c in display_cols if c in show.columns]

    st.dataframe(
        show[display_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "forecast_material_code":  st.column_config.TextColumn("Material Code"),
            "forecast_date":           st.column_config.DateColumn("Forecast Date"),
            "forecast_month":          st.column_config.TextColumn("Forecast Month"),
            "replenishment_date":      st.column_config.DateColumn("Replenishment Date"),
            "sales_person":            st.column_config.TextColumn("Sales Owner"),
            "Cur_Wk_Customer_Frcst":   st.column_config.NumberColumn("CW Customer",    format="%d"),
            "Cur_Wk_Statistical_Frcst":st.column_config.NumberColumn("CW Statistical", format="%d"),
            "90_Day_Customer_Frcst":   st.column_config.NumberColumn("90D Customer",   format="%d"),
            "90_Day_Statistical_Frcst":st.column_config.NumberColumn("90D Statistical",format="%d"),
            # material_customer 조인 컬럼
            "mc_segment":    st.column_config.TextColumn("Segment"),
            "mc_channel":    st.column_config.TextColumn("Channel"),
            "mc_customer":   st.column_config.TextColumn("Customer"),
            "mc_category":   st.column_config.TextColumn("Category"),
            "mc_product":    st.column_config.TextColumn("Product"),
            "mc_group_size": st.column_config.TextColumn("Group Size"),
            "mc_part_number":st.column_config.TextColumn("Part Number"),
        },
    )
    joined_cnt = show["mc_segment"].notna().sum() if "mc_segment" in show.columns else 0
    unmatched = len(show) - joined_cnt
    st.markdown(
        f"{len(show):,} row(s) · "
        f"{joined_cnt:,} matched in **material_customer** / "
        f"<span style='color:#d32f2f;font-weight:700;'>{unmatched:,} unmatched (LEFT JOIN)</span>",
        unsafe_allow_html=True,
    )
    
# ── Chart: grouped bar per sales owner ────────────────────────────────────────

if n_rows:
    st.markdown('<p class="fp-section">📊 Forecast by Sales Owner</p>', unsafe_allow_html=True)
    chart_df = df.assign(
        _owner=df["sales_person"].fillna("").astype(str).str.strip().replace("", "Unassigned")
    )
    agg_rows = []
    for col in FRCST_COLS:
        if col not in chart_df.columns:
            continue
        tmp = (
            chart_df.assign(_v=to_int_series(chart_df[col]))
            .loc[lambda d: d["_v"].notna()]
            .groupby("_owner", as_index=False)["_v"]
            .sum()
        )
        tmp["series"] = FRCST_LABELS[col]
        tmp = tmp.rename(columns={"_owner": "Sales Owner", "_v": "Qty"})
        agg_rows.append(tmp)

    if agg_rows:
        agg = pd.concat(agg_rows, ignore_index=True)
        fig = px.bar(
            agg, x="Sales Owner", y="Qty", color="series",
            barmode="group", text_auto=",.0f",
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig.update_layout(
            margin=dict(l=10, r=10, t=30, b=10),
            height=250, legend_title_text="",
            plot_bgcolor="rgba(255,255,255,0.4)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        fig.update_xaxes()
        st.plotly_chart(fig, use_container_width=True)

# ── Entry tabs ────────────────────────────────────────────────────────────────



with st.expander("Raw MariaDB result"):
    st.caption(f"{len(df_raw):,} row(s) from `forecast_planner`.")
    st.dataframe(df_raw, use_container_width=True)

st.markdown("---")
st.caption(f"Database: **ES_USER** · table **forecast_planner** · config **{CONFIG_PATH.name}**")
st.markdown(
    "<div style='text-align:center;color:#aaa;font-size:.78rem;padding:10px;'>"
    "© 2026 Hankook &amp; Company ES America Corp. &nbsp;|&nbsp; Forecast Planner"
    "</div>",
    unsafe_allow_html=True,
)
