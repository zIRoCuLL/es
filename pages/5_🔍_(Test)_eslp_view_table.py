import json
from pathlib import Path
from datetime import date, datetime

import pandas as pd
import streamlit as st
import oracledb


st.set_page_config(
    page_title="TP ES ESLPPROD DB Table Viewer",
    layout="wide"
)

st.markdown(
    """
<style>
    .section-title {
        font-size: 20px;
        font-weight: 700;
        color: #1a1a2e;
        margin-bottom: 10px;
        padding-bottom: 6px;
        border-bottom: 2px solid #dce6f0;
    }
</style>
""",
    unsafe_allow_html=True,
)


# =========================================================
# Config / Common functions
# =========================================================
CONFIG_PATH = Path("/home/habx/project/es/info_config/eslpprod_db.json")

# V_ES_SALES_ORD_ITEM pivot row dimensions (OE/RE: leading char O/R in SALES_ITEM_IDX)
PIVOT_ROWS_SALES_ITEM = [
    "OE/RE",
    "SOLD_TO_PARTNER",
    "SOLD_TO_NAME",
    "MAT_F003TX",
    "VSBED",
]


def load_db_config(config_path: Path) -> dict:
    """Load Oracle DB connection config from JSON."""
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    required_keys = ["host", "port", "service_name", "user", "password"]
    missing_keys = [key for key in required_keys if key not in config]
    if missing_keys:
        raise KeyError(f"Missing keys in config file: {missing_keys}")

    return config


@st.cache_resource
def get_connection():
    """Return an Oracle DB connection object."""
    config = load_db_config(CONFIG_PATH)

    dsn = oracledb.makedsn(
        host=config["host"],
        port=int(config["port"]),
        service_name=config["service_name"]
    )

    conn = oracledb.connect(
        user=config["user"],
        password=config["password"],
        dsn=dsn
    )
    return conn


@st.cache_data(ttl=300)
def run_query(
    sql: str,
    params: dict | None = None,
    dtype: dict | None = None,
) -> pd.DataFrame:
    """Execute a query and return a DataFrame. ``dtype`` is passed directly to ``pd.read_sql``."""
    conn = get_connection()
    if dtype:
        return pd.read_sql(sql, conn, params=params, dtype=dtype)
    return pd.read_sql(sql, conn, params=params)


def normalize_sales_ord_line_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize VBELN/POSNR columns to avoid integer conversion errors on blank values."""
    out = df.copy()
    if "POSNR" in out.columns:
        s = out["POSNR"].astype(str).str.strip()
        s = s.replace(["", "nan", "None", "<NA>"], pd.NA)
        out["POSNR"] = pd.to_numeric(s, errors="coerce").astype("Int64")
    if "VBELN" in out.columns:
        v = out["VBELN"].astype(str).str.strip()
        out["VBELN"] = v.replace(["", "nan", "None", "<NA>"], pd.NA)
    return out


def dedupe_sales_ord_item_df(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Keep one row per line key in V_ES_SALES_ORD_ITEM (most recent ITEM_UPD_DT/ITEM_REG_DT first).

    The view should be unique by ITEM_LATEST, but source/snapshot differences
    may introduce duplicates that are cleaned up here.
    """
    if df.empty:
        return df, 0
    n0 = len(df)
    if "SALES_ITEM_IDX" in df.columns:
        subset = ["SALES_ITEM_IDX"]
    elif "VBELN" in df.columns and "POSNR" in df.columns:
        subset = ["VBELN", "POSNR"]
    else:
        return df, 0
    sort_cols = [c for c in ("ITEM_UPD_DT", "ITEM_REG_DT") if c in df.columns]
    out = df.copy()
    if sort_cols:
        out = out.sort_values(
            by=sort_cols,
            ascending=[False] * len(sort_cols),
            na_position="last",
            kind="mergesort",
        )
    out = out.drop_duplicates(subset=subset, keep="first")
    return out, n0 - len(out)


def add_oe_re_from_sales_item_idx(df: pd.DataFrame) -> pd.DataFrame:
    """Classify OE/RE based on the first character of SALES_ITEM_IDX (O→OE, R→RE, else Other)."""
    col = "SALES_ITEM_IDX"
    if col not in df.columns:
        return df
    out = df.copy()
    head = out[col].astype(str).str.strip().str[:1].str.upper()
    out["OE/RE"] = head.map({"O": "OE", "R": "RE"}).fillna("Other")
    return out


def safe_to_datetime_yyyymmdd(df: pd.DataFrame, col_name: str) -> pd.DataFrame:
    """Convert a YYYYMMDD string column to datetime."""
    if col_name in df.columns:
        try:
            df[col_name] = pd.to_datetime(df[col_name].astype(str), format="%Y%m%d", errors="coerce")
        except Exception:
            pass
    return df


def series_to_datetime_flexible(series: pd.Series) -> pd.Series:
    """Return datetime series: pass through if already datetime, else try YYYYMMDD then general parse."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    parsed = pd.to_datetime(series.astype(str), format="%Y%m%d", errors="coerce")
    if parsed.notna().any():
        return parsed
    return pd.to_datetime(series, errors="coerce")


def iso_week_label(series: pd.Series) -> pd.Series:
    """ISO week label (e.g. 2026-W03), NaT-safe."""
    iso = series.dt.isocalendar()
    result = (
        iso["year"].astype("Int64").astype(str)
        + "-W"
        + iso["week"].astype("Int64").astype(str).str.zfill(2)
    )
    result[series.isna()] = None
    return result


def style_sales_ord_pivot(pv: pd.DataFrame, margin_name: str = "Total"):
    """Apply Blues gradient to data cells and highlight Total row/column."""
    d_cols = [c for c in pv.columns if c != margin_name]
    d_rows = [r for r in pv.index if margin_name not in str(r)]
    s = pv.style.format("{:,}")
    if d_rows and d_cols:
        s = s.background_gradient(
            cmap="Blues",
            subset=pd.IndexSlice[d_rows, d_cols],
            axis=None,
        )
    s = s.apply(
        lambda row: [
            "background-color:#1a1a2e;color:white;font-weight:bold;"
            if margin_name in str(row.name)
            else ""
            for _ in row
        ],
        axis=1,
    ).apply(
        lambda col: [
            "background-color:#dce6f0;font-weight:bold;"
            if col.name == margin_name
            else ""
            for _ in col
        ],
        axis=0,
    )
    return s


def show_dataframe_with_download(df: pd.DataFrame, file_prefix: str):
    """Display dataframe with row count and CSV download button."""
    st.write(f"Records: **{len(df):,}**")

    st.dataframe(
        df,
        use_container_width=True,
        height=200
    )

    csv_data = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="Download CSV",
        data=csv_data,
        file_name=f"{file_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv"
    )


# =========================================================
# UI
# =========================================================
st.title("TP ES ESLPPROD DB Table Viewer")
st.caption("Query V_ES_SALES_ORD_ITEM / V_ES_MATRL_STOCK_BARCODE")

# Default start date: 1st day of 3 months ago
today = datetime.today().date()
_y, _m = today.year, today.month
_m -= 3
while _m <= 0:
    _m += 12
    _y -= 1
default_start_date = date(_y, _m, 1)

tab1, tab2 = st.tabs([
    "V_ES_SALES_ORD_ITEM",
    "V_ES_MATRL_STOCK_BARCODE"
])

# =========================================================
# TAB 1 : V_ES_SALES_ORD_ITEM
# Filter by ITEM_REG_DT (YYYYMMDD string)
# =========================================================
with tab1:
    st.subheader("V_ES_SALES_ORD_ITEM")
    st.write("Filter: `ITEM_REG_DT` from start date to end date")

    col1, col2, col3 = st.columns([1, 1, 0.6])

    with col1:
        sales_start_date = st.date_input(
            "ITEM_REG_DT Start",
            value=default_start_date,
            key="sales_start_date"
        )

    with col2:
        sales_end_date = st.date_input(
            "ITEM_REG_DT End",
            value=today,
            key="sales_end_date"
        )

    with col3:
        st.write("")
        st.write("")
        sales_fetch_button = st.button(
            "Search",
            key="sales_fetch_button",
            type="primary",
            use_container_width=True
        )

    if sales_start_date > sales_end_date:
        st.error("Start date cannot be later than end date.")
    else:
        if "sales_run_search" not in st.session_state:
            st.session_state.sales_run_search = True

        if sales_fetch_button:
            st.session_state.sales_run_search = True

        sql_sales = """
            SELECT *
            FROM V_ES_SALES_ORD_ITEM
            WHERE ITEM_REG_DT IS NOT NULL
              AND ITEM_REG_DT BETWEEN
                    TO_DATE(:start_date, 'YYYYMMDD')
                AND TO_DATE(:end_date, 'YYYYMMDD') + 0.99999
            ORDER BY ITEM_REG_DT DESC
        """

        if st.session_state.sales_run_search:
            try:
                df_sales = run_query(
                    sql_sales,
                    params={
                        "start_date": sales_start_date.strftime("%Y%m%d"),
                        "end_date": sales_end_date.strftime("%Y%m%d")
                    },
                    dtype={"POSNR": object, "VBELN": object},
                )
                df_sales = normalize_sales_ord_line_columns(df_sales)
                df_sales, dup_removed = dedupe_sales_ord_item_df(df_sales)
                df_sales = add_oe_re_from_sales_item_idx(df_sales)
                if dup_removed > 0:
                    st.warning(
                        f"**{dup_removed:,}** duplicate rows removed (same SALES_ITEM_IDX). "
                        "Kept the most recent `ITEM_UPD_DT` → `ITEM_REG_DT`."
                    )
                df_sales = safe_to_datetime_yyyymmdd(df_sales, "ITEM_REG_DT")
                show_dataframe_with_download(df_sales, "V_ES_SALES_ORD_ITEM")

                st.markdown("---")
                st.markdown(
                    '<div class="section-title">📋 Pivot Table — Weekly Orders '
                    "(ORD_ERDAT weekly × KWMENG)</div>",
                    unsafe_allow_html=True,
                )

                pivot_rows = [c for c in PIVOT_ROWS_SALES_ITEM if c in df_sales.columns]
                pivot_needed_values = ["ORD_ERDAT", "KWMENG"]
                missing_vals = [c for c in pivot_needed_values if c not in df_sales.columns]
                if not pivot_rows:
                    st.warning("Pivot row dimension columns not found in result.")
                elif missing_vals:
                    st.warning(
                        "Required pivot columns not found in result: "
                        + ", ".join(missing_vals)
                    )
                else:
                    df_pv = df_sales.copy()
                    df_pv["ORD_ERDAT"] = series_to_datetime_flexible(df_pv["ORD_ERDAT"])
                    df_pv["KWMENG"] = pd.to_numeric(df_pv["KWMENG"], errors="coerce").fillna(0)
                    df_pv["order_week"] = iso_week_label(df_pv["ORD_ERDAT"])
                    pv1_data = df_pv.dropna(subset=["order_week"]).copy()
                    if pv1_data.empty:
                        st.info("No valid ORD_ERDAT rows — pivot cannot be generated.")
                    else:
                        week_order = sorted(
                            [
                                x
                                for x in pv1_data["order_week"].unique()
                                if isinstance(x, str)
                                and "-W" in x
                                and str(x) not in ("nan", "None", "<NA>", "")
                            ],
                            key=lambda x: int(x.split("-W")[0]) * 100 + int(x.split("-W")[1]),
                        )

                        pv1 = pv1_data.pivot_table(
                            index=pivot_rows,
                            columns="order_week",
                            values="KWMENG",
                            aggfunc="sum",
                            fill_value=0,
                            margins=True,
                            margins_name="Total",
                        ).round(0).astype(int)

                        pv_flat = pv1.reset_index()
                        first_dim = pivot_rows[0]
                        pv_flat["_m_last"] = (
                            pv_flat[first_dim].astype(str) == "Total"
                        ).astype(int)

                        sort_keys = ["_m_last"]
                        sort_asc = [True]
                        drop_tmp = ["_m_last"]

                        if "OE/RE" in pivot_rows:
                            def _oe_re_sort_rank(v) -> int:
                                t = str(v)
                                if t == "Total":
                                    return 999
                                return {"OE": 0, "RE": 1, "Other": 2}.get(t, 3)

                            pv_flat["_oe_pri"] = pv_flat["OE/RE"].map(_oe_re_sort_rank)
                            sort_keys.append("_oe_pri")
                            sort_asc.append(True)
                            drop_tmp.append("_oe_pri")

                        if "SOLD_TO_NAME" in pivot_rows and "SOLD_TO_NAME" in pv_flat.columns:
                            sort_keys.append("SOLD_TO_NAME")
                            sort_asc.append(True)

                        sort_keys.append("Total")
                        sort_asc.append(False)

                        for c in pivot_rows:
                            if c not in ("OE/RE", "SOLD_TO_NAME") and c in pv_flat.columns:
                                sort_keys.append(c)
                                sort_asc.append(True)

                        pv_flat = pv_flat.sort_values(
                            by=sort_keys,
                            ascending=sort_asc,
                            kind="mergesort",
                        ).drop(columns=drop_tmp)
                        pv1 = pv_flat.set_index(pivot_rows)

                        week_cols_ordered = [c for c in week_order if c in pv1.columns]
                        ordered_cols = ["Total"] + week_cols_ordered
                        pv1 = pv1.reindex(columns=ordered_cols)

                        st.write(f"Pivot rows: **{len(pv1):,}** (including Total row)")
                        st.dataframe(
                            style_sales_ord_pivot(pv1),
                            use_container_width=True,
                            height=min(38 * (len(pv1) + 2) + 40, 500),
                        )

                        csv_pivot = pv1.reset_index().to_csv(index=False).encode("utf-8-sig")
                        st.download_button(
                            label="Download Weekly KWMENG Pivot CSV",
                            data=csv_pivot,
                            file_name=(
                                "V_ES_SALES_ORD_ITEM_KWMENG_WEEKLY_"
                                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                            ),
                            mime="text/csv",
                        )
            except Exception as e:
                st.error(f"Error querying V_ES_SALES_ORD_ITEM: {e}")

# =========================================================
# TAB 2 : V_ES_MATRL_STOCK_BARCODE
# Filter by PRODUCT_DATE (YYYYMMDD string)
# =========================================================
with tab2:
    st.subheader("V_ES_MATRL_STOCK_BARCODE")
    st.write("Filter: `PRODUCT_DATE` from start date to end date")

    col1, col2, col3 = st.columns([1, 1, 0.6])

    with col1:
        stock_start_date = st.date_input(
            "PRODUCT_DATE Start",
            value=default_start_date,
            key="stock_start_date"
        )

    with col2:
        stock_end_date = st.date_input(
            "PRODUCT_DATE End",
            value=today,
            key="stock_end_date"
        )

    with col3:
        st.write("")
        st.write("")
        stock_fetch_button = st.button(
            "Search",
            key="stock_fetch_button",
            type="primary",
            use_container_width=True
        )

    if stock_start_date > stock_end_date:
        st.error("Start date cannot be later than end date.")
    else:
        if "stock_run_search" not in st.session_state:
            st.session_state.stock_run_search = True

        if stock_fetch_button:
            st.session_state.stock_run_search = True

        sql_stock = """
            SELECT *
            FROM V_ES_MATRL_STOCK_BARCODE
            WHERE PRODUCT_DATE IS NOT NULL
              AND PRODUCT_DATE BETWEEN :start_date AND :end_date
            ORDER BY PRODUCT_DATE DESC
        """

        if st.session_state.stock_run_search:
            try:
                query_params = {
                    "start_date": stock_start_date.strftime("%Y%m%d"),
                    "end_date": stock_end_date.strftime("%Y%m%d")
                }

                df_stock = run_query(sql_stock, params=query_params)
                df_stock = safe_to_datetime_yyyymmdd(df_stock, "PRODUCT_DATE")

                # Raw data
                show_dataframe_with_download(df_stock, "V_ES_MATRL_STOCK_BARCODE")

                # Monthly aggregation below raw data
                st.markdown("---")
                st.subheader("Monthly SUM(QTY) by CUST_PART_NO")

                sql_qty_summary = """
                    SELECT
                        CUST_PART_NO,
                        SUBSTR(PRODUCT_DATE, 1, 6) AS YM,
                        SUM(QTY) AS QTY
                    FROM V_ES_MATRL_STOCK_BARCODE
                    WHERE PRODUCT_DATE IS NOT NULL
                      AND PRODUCT_DATE BETWEEN :start_date AND :end_date
                      AND CUST_PART_NO IS NOT NULL
                    GROUP BY CUST_PART_NO, SUBSTR(PRODUCT_DATE, 1, 6)
                    ORDER BY CUST_PART_NO, YM
                """

                df_qty_summary = run_query(sql_qty_summary, params=query_params)

                if df_qty_summary.empty:
                    st.info("No monthly aggregation data found.")
                else:
                    df_qty_pivot = df_qty_summary.pivot_table(
                        index="CUST_PART_NO",
                        columns="YM",
                        values="QTY",
                        aggfunc="sum",
                        fill_value=0
                    ).reset_index()

                    month_cols = sorted([col for col in df_qty_pivot.columns if col != "CUST_PART_NO"])
                    df_qty_pivot = df_qty_pivot[["CUST_PART_NO"] + month_cols]

                    st.write(f"Aggregated rows: **{len(df_qty_pivot):,}**")
                    st.dataframe(
                        df_qty_pivot,
                        use_container_width=True,
                        height=400
                    )

                    csv_summary = df_qty_pivot.to_csv(index=False).encode("utf-8-sig")
                    st.download_button(
                        label="Download Monthly Summary CSV",
                        data=csv_summary,
                        file_name=f"V_ES_MATRL_STOCK_BARCODE_MONTHLY_QTY_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )

            except Exception as e:
                st.error(f"Error querying V_ES_MATRL_STOCK_BARCODE: {e}")

st.markdown("---")
st.write("※ Oracle connection settings: `/home/habx/project/es/info_config/eslpprod_db.json`")
st.markdown(
    "<div style='text-align:center;color:#aaa;font-size:.78rem;padding:10px;'>"
    "© 2026 Hankook &amp; Company ES America Corp. &nbsp;|&nbsp; ESLP View Table (Test)"
    "</div>",
    unsafe_allow_html=True,
)
