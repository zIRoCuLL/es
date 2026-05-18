"""
Test page — ES_USER MariaDB 데이터 확인
 · es_if_gsheet_nashville_warehouse
 · es_if_vizion_us_intransit
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import pymysql
import streamlit as st

BASE_DIR    = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "info_config" / "mariadb_es_user.json"

sys.path.insert(0, str(BASE_DIR))
from utils.access_logger import log_access

st.set_page_config(
    page_title="Data to MariaDB — Test",
    page_icon="🗄️",
    layout="wide",
    initial_sidebar_state="expanded",
)
log_access("Data to MariaDB")

st.markdown("""
<style>
    .main { background: linear-gradient(180deg,#f0f4fa 0%,#f7f8fc 100%); }
    .block-container { padding-top:1.2rem; padding-bottom:2.5rem; }
    .db-hero {
        background: linear-gradient(135deg,#1a2a4a 0%,#2d4a7a 50%,#3d6aaa 100%);
        color:#fff; border-radius:14px; padding:1.1rem 1.6rem;
        margin-bottom:1.2rem; box-shadow:0 8px 32px rgba(26,42,74,0.28);
    }
    .db-hero h1 { margin:0; font-size:1.6rem; font-weight:800; }
    .db-hero p  { margin:.4rem 0 0; opacity:.9; font-size:.9rem; }
    .db-section {
        font-size:1.05rem; font-weight:700; color:#1a2a4a;
        margin:1.2rem 0 .5rem; padding-bottom:5px;
        border-bottom:2px solid #c5d4e8;
    }
    .db-badge {
        display:inline-block; background:#e8f0fb; color:#1a2a4a;
        border-radius:6px; padding:2px 10px; font-size:.78rem;
        font-weight:700; margin-left:8px; vertical-align:middle;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="db-hero">
  <h1>🗄️ Data to MariaDB — Test</h1>
  <p>ES_USER · nashville_warehouse (Google Sheet sync) &amp; vizion_us_intransit (Vizion web sync)</p>
</div>
""", unsafe_allow_html=True)


# ── DB connection ──────────────────────────────────────────────────────────────

@contextmanager
def db_conn():
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    conn = pymysql.connect(
        host=cfg["host"], port=int(cfg.get("port", 3306)),
        user=cfg["user"], password=cfg.get("password", ""),
        database=cfg["database"], charset="utf8mb4", autocommit=True,
    )
    try:
        yield conn
    finally:
        conn.close()


def query_df(sql: str, params=None) -> pd.DataFrame:
    with db_conn() as conn:
        return pd.read_sql(sql, conn, params=params)


def table_row_count(table: str) -> int:
    try:
        df = query_df(f"SELECT COUNT(*) AS cnt FROM `{table}`")
        return int(df["cnt"].iloc[0])
    except Exception:
        return -1


# ── Tabs ───────────────────────────────────────────────────────────────────────

tab_gsheet, tab_vizion = st.tabs([
    "📦 Nashville Warehouse (GSheet)",
    "🚢 Vizion US In-Transit",
])

# ══════════════════════════════════════════════════════════════════════════════
# Tab 1 — es_if_gsheet_nashville_warehouse
# ══════════════════════════════════════════════════════════════════════════════
with tab_gsheet:
    TABLE_GS = "es_if_gsheet_nashville_warehouse"

    st.markdown(
        f'<p class="db-section">📦 <code>{TABLE_GS}</code>'
        f'<span class="db-badge">Google Sheet → MariaDB</span></p>',
        unsafe_allow_html=True,
    )

    # ── 필터 ────────────────────────────────────────────────────────────────
    with st.expander("🔍 Filter", expanded=True):
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            flt_item = st.text_input("Item", placeholder="Search item…", key="gs_item")
        with fc2:
            flt_lot  = st.text_input("Lot", placeholder="Search lot…",  key="gs_lot")
        with fc3:
            flt_cont = st.text_input("Container", placeholder="Search container…", key="gs_cont")

    # ── Load data ────────────────────────────────────────────────────────────
    try:
        total = table_row_count(TABLE_GS)
        sql = f"""
            SELECT id, item, lot, container, receipt_date, shipping_date,
                   trailer, shipping_order, remark,
                   order_qty, average_qty, stock, total_pallet_quantity,
                   order_number, costomer_code, tracking_code, synced_at
            FROM `{TABLE_GS}`
            ORDER BY id DESC
            LIMIT 5000
        """
        df_gs = query_df(sql)

        # Apply filters
        if flt_item.strip():
            df_gs = df_gs[df_gs["item"].astype(str).str.contains(flt_item.strip(), case=False, na=False)]
        if flt_lot.strip():
            df_gs = df_gs[df_gs["lot"].astype(str).str.contains(flt_lot.strip(), case=False, na=False)]
        if flt_cont.strip():
            df_gs = df_gs[df_gs["container"].astype(str).str.contains(flt_cont.strip(), case=False, na=False)]

        st.caption(f"**{len(df_gs):,}** rows shown / **{total:,}** total in DB · last synced per `synced_at`")

        st.dataframe(
            df_gs,
            use_container_width=True,
            hide_index=True,
            column_config={
                "id":                    st.column_config.NumberColumn("ID",         format="%d"),
                "item":                  st.column_config.TextColumn("Item"),
                "lot":                   st.column_config.TextColumn("Lot"),
                "container":             st.column_config.TextColumn("Container"),
                "receipt_date":          st.column_config.TextColumn("Receipt Date"),
                "shipping_date":         st.column_config.TextColumn("Shipping Date"),
                "trailer":               st.column_config.TextColumn("Trailer"),
                "shipping_order":        st.column_config.TextColumn("Shipping Order"),
                "remark":                st.column_config.TextColumn("Remark"),
                "order_qty":             st.column_config.NumberColumn("Order Qty",           format="%.0f"),
                "average_qty":           st.column_config.NumberColumn("Average Qty",         format="%.2f"),
                "stock":                 st.column_config.NumberColumn("Stock",               format="%.0f"),
                "total_pallet_quantity": st.column_config.NumberColumn("Total Pallet Qty",    format="%.0f"),
                "order_number":          st.column_config.TextColumn("Order Number"),
                "costomer_code":         st.column_config.TextColumn("Customer Code"),
                "tracking_code":         st.column_config.TextColumn("Tracking Code"),
                "synced_at":             st.column_config.DatetimeColumn("Synced At"),
            },
        )
    except Exception as e:
        st.error(f"Failed to load `{TABLE_GS}`: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# Tab 2 — es_if_vizion_us_intransit
# ══════════════════════════════════════════════════════════════════════════════
with tab_vizion:
    TABLE_VZ = "es_if_vizion_us_intransit"

    st.markdown(
        f'<p class="db-section">🚢 <code>{TABLE_VZ}</code>'
        f'<span class="db-badge">Vizion → MariaDB</span></p>',
        unsafe_allow_html=True,
    )

    # ── 필터 ────────────────────────────────────────────────────────────────
    with st.expander("🔍 Filter", expanded=True):
        vc1, vc2, vc3, vc4 = st.columns(4)
        with vc1:
            flt_id   = st.text_input("Identifier", placeholder="Booking / BL / Container", key="vz_id")
        with vc2:
            flt_carr = st.text_input("Carrier", placeholder="e.g. CMDU", key="vz_carr")
        with vc3:
            flt_stat = st.selectbox("Status", ["(All)", "IN_TRANSIT", "ARRIVED", "COMPLETED", "UNKNOWN"],
                                    key="vz_stat")
        with vc4:
            flt_act  = st.selectbox("Active", ["(All)", "Active only", "Inactive only"], key="vz_act")

    # ── Load data ────────────────────────────────────────────────────────────
    try:
        total_vz = table_row_count(TABLE_VZ)
        sql_vz = f"""
            SELECT
                shipment_id, identifier, carrier_code, shipment_type,
                status, current_phase_name,
                vizion_bill_of_lading, vizion_container_number, vizion_booking_number,
                pol_location_name, pol_location_unique_id, pol_departure_timestamp,
                pod_location_name, pod_location_unique_id, pod_arrival_timestamp,
                last_free_date,
                current_event, current_event_timestamp, current_event_location,
                current_vessel, current_voyage,
                is_active, ref_created_at, ref_updated_at, synced_at
            FROM `{TABLE_VZ}`
            ORDER BY ref_updated_at DESC
        """
        df_vz = query_df(sql_vz)

        # Apply filters
        if flt_id.strip():
            mask = (
                df_vz["identifier"].astype(str).str.contains(flt_id.strip(), case=False, na=False) |
                df_vz["vizion_container_number"].astype(str).str.contains(flt_id.strip(), case=False, na=False) |
                df_vz["vizion_bill_of_lading"].astype(str).str.contains(flt_id.strip(), case=False, na=False)
            )
            df_vz = df_vz[mask]
        if flt_carr.strip():
            df_vz = df_vz[df_vz["carrier_code"].astype(str).str.contains(flt_carr.strip(), case=False, na=False)]
        if flt_stat != "(All)":
            df_vz = df_vz[df_vz["status"] == flt_stat]
        if flt_act == "Active only":
            df_vz = df_vz[df_vz["is_active"] == 1]
        elif flt_act == "Inactive only":
            df_vz = df_vz[df_vz["is_active"] == 0]

        # Active badge
        df_vz["active_label"] = df_vz["is_active"].apply(lambda v: "✅ Active" if v else "⛔ Inactive")

        st.caption(f"**{len(df_vz):,}** rows shown / **{total_vz:,}** total in DB")

        display_cols = [
            "identifier", "carrier_code", "shipment_type", "status",
            "current_phase_name",
            "vizion_bill_of_lading", "vizion_container_number", "vizion_booking_number",
            "pol_location_unique_id", "pol_location_name", "pol_departure_timestamp",
            "pod_location_unique_id", "pod_location_name", "pod_arrival_timestamp",
            "last_free_date",
            "current_event", "current_event_timestamp", "current_event_location",
            "current_vessel", "current_voyage",
            "active_label", "ref_updated_at", "synced_at",
        ]

        st.dataframe(
            df_vz[display_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "identifier":               st.column_config.TextColumn("Identifier"),
                "carrier_code":             st.column_config.TextColumn("Carrier"),
                "shipment_type":            st.column_config.TextColumn("Type"),
                "status":                   st.column_config.TextColumn("Status"),
                "current_phase_name":       st.column_config.TextColumn("Phase"),
                "vizion_bill_of_lading":    st.column_config.TextColumn("B/L"),
                "vizion_container_number":  st.column_config.TextColumn("Container"),
                "vizion_booking_number":    st.column_config.TextColumn("Booking"),
                "pol_location_unique_id":   st.column_config.TextColumn("POL Code"),
                "pol_location_name":        st.column_config.TextColumn("POL Name"),
                "pol_departure_timestamp":  st.column_config.DatetimeColumn("POL Departure"),
                "pod_location_unique_id":   st.column_config.TextColumn("POD Code"),
                "pod_location_name":        st.column_config.TextColumn("POD Name"),
                "pod_arrival_timestamp":    st.column_config.DatetimeColumn("POD Arrival"),
                "last_free_date":           st.column_config.TextColumn("Last Free Date"),
                "current_event":            st.column_config.TextColumn("Latest Event"),
                "current_event_timestamp":  st.column_config.DatetimeColumn("Event Time"),
                "current_event_location":   st.column_config.TextColumn("Event Location"),
                "current_vessel":           st.column_config.TextColumn("Vessel"),
                "current_voyage":           st.column_config.TextColumn("Voyage"),
                "active_label":             st.column_config.TextColumn("Active"),
                "ref_updated_at":           st.column_config.DatetimeColumn("Updated At"),
                "synced_at":                st.column_config.DatetimeColumn("Synced At"),
            },
        )
    except Exception as e:
        st.error(f"Failed to load `{TABLE_VZ}`: {e}")

st.markdown("---")
st.caption(f"Database: **ES_USER** · config **{CONFIG_PATH.name}**")

# ══════════════════════════════════════════════════════════════════════════════
# 마지막 Sync 로그
# ══════════════════════════════════════════════════════════════════════════════

LOGS_DIR = BASE_DIR / "logs"

LOG_META = {
    "gsheet": {
        "file":  LOGS_DIR / "gsheet_nashville_warehouse_sync.log",
        "start": "Nashville Warehouse GSheet Sync START",
        "label": "📦 Google Sheet (Nashville Warehouse) — Last Sync Log",
    },
    "vizion": {
        "file":  LOGS_DIR / "vizion_intransit_sync.log",
        "start": "Vizion US In-Transit Sync START",
        "label": "🚢 Vizion US In-Transit — Last Sync Log",
    },
}


def _log_level_color(line: str) -> str:
    if "[ERROR]" in line or "[CRITICAL]" in line:
        return "#fff0f0"
    if "[WARNING]" in line or "[WARN]" in line:
        return "#fffbe6"
    return ""


def render_last_sync_log(meta: dict) -> None:
    log_path = meta["file"]
    if not log_path.exists():
        st.info(f"Log file not found: `{log_path.name}`")
        return

    raw_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()

    # 연속 중복 제거
    deduped: list[str] = []
    for ln in raw_lines:
        if not deduped or ln != deduped[-1]:
            deduped.append(ln)

    # 마지막 START 위치 찾기
    start_idx = None
    for i in range(len(deduped) - 1, -1, -1):
        if meta["start"] in deduped[i]:
            start_idx = i
            break

    if start_idx is None:
        st.warning("START marker not found.")
        return

    session_lines = deduped[start_idx:]

    # 타임스탬프·레벨·메시지 파싱해서 표 구성
    rows = []
    for ln in session_lines:
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split(" ", 3)   # 날짜 시간 [LEVEL] 메시지
        if len(parts) >= 4:
            ts  = f"{parts[0]} {parts[1]}"
            lvl = parts[2].strip("[]")
            msg = parts[3]
        elif len(parts) == 3:
            ts  = f"{parts[0]} {parts[1]}"
            lvl = parts[2].strip("[]")
            msg = ""
        else:
            ts, lvl, msg = "", "INFO", ln
        rows.append({"Time": ts, "Level": lvl, "Message": msg})

    import pandas as _pd
    df_log = _pd.DataFrame(rows)

    # 요약 배지
    is_error   = df_log["Level"].isin(["ERROR", "CRITICAL"]).any()
    is_warning = df_log["Level"].isin(["WARNING", "WARN"]).any()
    if is_error:
        badge_html = '<span style="background:#f8d7da;color:#721c24;border-radius:4px;padding:2px 10px;font-size:.8rem;font-weight:700;">⚠️ ERROR</span>'
    elif is_warning:
        badge_html = '<span style="background:#fff3cd;color:#856404;border-radius:4px;padding:2px 10px;font-size:.8rem;font-weight:700;">⚠️ WARNING</span>'
    else:
        badge_html = '<span style="background:#d4edda;color:#155724;border-radius:4px;padding:2px 10px;font-size:.8rem;font-weight:700;">✔ OK</span>'

    last_ts = df_log["Time"].iloc[-1] if not df_log.empty else "N/A"

    st.markdown(
        f'<div style="font-size:.95rem;font-weight:700;color:#1a2a4a;margin:.6rem 0 .3rem;">'
        f'{meta["label"]} &nbsp;{badge_html}'
        f'<span style="font-size:.78rem;color:#888;font-weight:400;margin-left:12px;">Last record: {last_ts}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.dataframe(
        df_log,
        use_container_width=True,
        hide_index=True,
        height=min(35 * len(df_log) + 38, 320),
        column_config={
            "Time":    st.column_config.TextColumn("Time",    width="medium"),
            "Level":   st.column_config.TextColumn("Level",   width="small"),
            "Message": st.column_config.TextColumn("Message", width="large"),
        },
    )


st.markdown("### 🗒️ Last Sync Log")
log_col1, log_col2 = st.columns(2)

with log_col1:
    render_last_sync_log(LOG_META["gsheet"])

with log_col2:
    render_last_sync_log(LOG_META["vizion"])

st.markdown("---")
st.markdown(
    "<div style='text-align:center;color:#aaa;font-size:.78rem;padding:10px;'>"
    "© 2026 Hankook &amp; Company ES America Corp. &nbsp;|&nbsp; Data to MariaDB"
    "</div>",
    unsafe_allow_html=True,
)
