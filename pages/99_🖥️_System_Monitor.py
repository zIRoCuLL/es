"""
System & External Connection Monitoring Page
- System resources: CPU / Memory / Disk / Network
- External connections: MariaDB / Oracle DB / Vizion API / Google Sheet
"""

from __future__ import annotations

import json
import socket
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import psutil
import pymysql
import requests
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
from utils.access_logger import log_access

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="System Monitor",
    page_icon="🖥️",
    layout="wide",
    initial_sidebar_state="collapsed",
)
log_access("System Monitor")

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { background: linear-gradient(180deg,#f0f4fa 0%,#f7f8fc 100%); }
    .block-container { padding-top:1.2rem; padding-bottom:2.5rem; }

    .hero {
        background: linear-gradient(135deg,#1a2a4a 0%,#2d4a7a 50%,#3d6aaa 100%);
        color:#fff; border-radius:14px; padding:1.1rem 1.6rem;
        margin-bottom:1.2rem; box-shadow:0 8px 32px rgba(26,42,74,0.28);
        display:flex; align-items:center; justify-content:space-between;
    }
    .hero h1 { margin:0; font-size:1.6rem; font-weight:800; }
    .hero p  { margin:.3rem 0 0; opacity:.9; font-size:.85rem; }
    .hero .ts { font-size:.78rem; opacity:.75; text-align:right; }

    .section-title {
        font-size:1.05rem; font-weight:700; color:#1a2a4a;
        margin:1.4rem 0 .6rem; padding-bottom:5px;
        border-bottom:2px solid #c5d4e8;
    }

    .info-card {
        background:#fff; border-radius:10px; padding:.8rem 1rem;
        box-shadow:0 2px 8px rgba(0,0,0,.07); margin-bottom:.6rem;
    }
    .info-row { display:flex; justify-content:space-between; align-items:center;
                font-size:.88rem; padding:.15rem 0; }
    .info-label { color:#555; font-weight:600; }
    .info-value { color:#1a2a4a; font-weight:700; }

    .conn-card {
        background:#fff; border-radius:10px; padding:.9rem 1.1rem;
        box-shadow:0 2px 8px rgba(0,0,0,.07); margin-bottom:.7rem;
    }
    .conn-title { font-weight:700; color:#1a2a4a; font-size:.95rem; margin-bottom:.3rem; }
    .conn-detail { font-size:.8rem; color:#666; margin-top:.15rem; }

    .badge-ok   { background:#d4edda; color:#155724; border-radius:20px;
                  padding:2px 12px; font-size:.78rem; font-weight:700; }
    .badge-fail { background:#f8d7da; color:#721c24; border-radius:20px;
                  padding:2px 12px; font-size:.78rem; font-weight:700; }
    .badge-warn { background:#fff3cd; color:#856404; border-radius:20px;
                  padding:2px 12px; font-size:.78rem; font-weight:700; }

    .gauge-bar-wrap { background:#e8edf5; border-radius:20px; height:10px;
                      margin:.35rem 0 .1rem; overflow:hidden; }
    .gauge-bar      { height:10px; border-radius:20px; transition:width .4s; }
</style>
""", unsafe_allow_html=True)


# ── Utilities ─────────────────────────────────────────────────────────────────

def load_config(filename: str) -> dict:
    path = BASE_DIR / "info_config" / filename
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def gauge_html(pct: float, color: str = "#3d6aaa") -> str:
    """Gauge bar HTML for a given percentage."""
    if pct >= 90:
        color = "#dc3545"
    elif pct >= 70:
        color = "#fd7e14"
    return (
        f'<div class="gauge-bar-wrap">'
        f'<div class="gauge-bar" style="width:{pct:.1f}%;background:{color};"></div>'
        f"</div>"
    )


def badge(ok: bool | None, ok_text="Connected", fail_text="Failed", warn_text="Timeout") -> str:
    if ok is None:
        return f'<span class="badge-warn">{warn_text}</span>'
    if ok:
        return f'<span class="badge-ok">✔ {ok_text}</span>'
    return f'<span class="badge-fail">✖ {fail_text}</span>'


def fmt_bytes(n: float, suffix="B") -> str:
    for unit in ("", "K", "M", "G", "T"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}{suffix}"
        n /= 1024
    return f"{n:.1f} P{suffix}"


def uptime_str() -> str:
    boot = datetime.fromtimestamp(psutil.boot_time())
    delta = datetime.now() - boot
    days = delta.days
    hours, rem = divmod(delta.seconds, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


# ── Connection tests ──────────────────────────────────────────────────────────

@st.cache_data(ttl=30, show_spinner=False)
def test_mariadb(cfg: dict) -> tuple[bool, str, float]:
    t0 = time.perf_counter()
    try:
        conn = pymysql.connect(
            host=cfg["host"], port=int(cfg["port"]),
            user=cfg["user"], password=cfg["password"],
            database=cfg["database"], connect_timeout=5,
        )
        conn.close()
        elapsed = (time.perf_counter() - t0) * 1000
        return True, "OK", elapsed
    except Exception as e:
        return False, str(e)[:80], (time.perf_counter() - t0) * 1000


@st.cache_data(ttl=30, show_spinner=False)
def test_tcp(host: str, port: int, label: str) -> tuple[bool, str, float]:
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=5):
            elapsed = (time.perf_counter() - t0) * 1000
            return True, "OK", elapsed
    except Exception as e:
        return False, str(e)[:80], (time.perf_counter() - t0) * 1000


@st.cache_data(ttl=30, show_spinner=False)
def test_http(url: str, label: str) -> tuple[bool, str, float, int]:
    t0 = time.perf_counter()
    try:
        resp = requests.get(url, timeout=8, allow_redirects=True)
        elapsed = (time.perf_counter() - t0) * 1000
        ok = resp.status_code < 400
        return ok, f"HTTP {resp.status_code}", elapsed, resp.status_code
    except requests.Timeout:
        return None, "Timeout", (time.perf_counter() - t0) * 1000, 0
    except Exception as e:
        return False, str(e)[:80], (time.perf_counter() - t0) * 1000, 0


# ── Header ────────────────────────────────────────────────────────────────────

now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
st.markdown(f"""
<div class="hero">
  <div>
    <h1>🖥️ System Monitor</h1>
    <p>Real-time monitoring of system resources and external connection status</p>
  </div>
  <div class="ts">Last Updated<br><b>{now_str}</b></div>
</div>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════
# SECTION 1 — System Info
# ════════════════════════════════════════════════════════════════════

st.markdown('<div class="section-title">🖥️ System Info</div>', unsafe_allow_html=True)

sys_col1, sys_col2 = st.columns(2)

# ── CPU ──────────────────────────────────────────────────────────────
with sys_col1:
    cpu_pct = psutil.cpu_percent(interval=0.5)
    cpu_count = psutil.cpu_count(logical=True)
    cpu_phys  = psutil.cpu_count(logical=False)
    cpu_freq  = psutil.cpu_freq()
    freq_str  = f"{cpu_freq.current:.0f} MHz" if cpu_freq else "N/A"

    st.markdown(f"""
    <div class="info-card">
      <div style="font-weight:700;font-size:1rem;color:#1a2a4a;margin-bottom:.5rem;">
        🔵 CPU Usage &nbsp; <b style="font-size:1.3rem;">{cpu_pct:.1f}%</b>
      </div>
      {gauge_html(cpu_pct)}
      <div class="info-row"><span class="info-label">Physical Cores</span>
        <span class="info-value">{cpu_phys}</span></div>
      <div class="info-row"><span class="info-label">Logical Cores</span>
        <span class="info-value">{cpu_count}</span></div>
      <div class="info-row"><span class="info-label">Clock Speed</span>
        <span class="info-value">{freq_str}</span></div>
    </div>
    """, unsafe_allow_html=True)

    per_core = psutil.cpu_percent(interval=0.1, percpu=True)
    with st.expander("🔍 Per-core Usage", expanded=False):
        cols = st.columns(min(4, len(per_core)))
        for i, pct in enumerate(per_core):
            with cols[i % 4]:
                st.metric(f"Core {i}", f"{pct:.0f}%")

# ── Memory ───────────────────────────────────────────────────────────
with sys_col2:
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    st.markdown(f"""
    <div class="info-card">
      <div style="font-weight:700;font-size:1rem;color:#1a2a4a;margin-bottom:.5rem;">
        🟣 Memory Usage &nbsp; <b style="font-size:1.3rem;">{mem.percent:.1f}%</b>
      </div>
      {gauge_html(mem.percent)}
      <div class="info-row"><span class="info-label">Total</span>
        <span class="info-value">{fmt_bytes(mem.total)}</span></div>
      <div class="info-row"><span class="info-label">Used</span>
        <span class="info-value">{fmt_bytes(mem.used)}</span></div>
      <div class="info-row"><span class="info-label">Available</span>
        <span class="info-value">{fmt_bytes(mem.available)}</span></div>
      <hr style="margin:.4rem 0;border-color:#eee;">
      <div style="font-size:.82rem;color:#888;font-weight:600;">SWAP</div>
      {gauge_html(swap.percent, "#8950fc")}
      <div class="info-row"><span class="info-label">SWAP Used</span>
        <span class="info-value">{fmt_bytes(swap.used)} / {fmt_bytes(swap.total)}</span></div>
    </div>
    """, unsafe_allow_html=True)

# ── Disk & Server Info ────────────────────────────────────────────────
disk_col, sysinfo_col = st.columns(2)

with disk_col:
    st.markdown('<div style="font-size:.9rem;font-weight:700;color:#1a2a4a;margin-bottom:.4rem;">💾 Disk Usage</div>', unsafe_allow_html=True)
    try:
        partitions = [p for p in psutil.disk_partitions() if p.fstype]
        for part in partitions[:4]:
            try:
                usage = psutil.disk_usage(part.mountpoint)
                st.markdown(f"""
                <div class="info-card" style="padding:.6rem .9rem;">
                  <div style="font-size:.82rem;font-weight:700;color:#444;">
                    {part.mountpoint} <span style="color:#888;font-weight:400;">({part.fstype})</span>
                  </div>
                  {gauge_html(usage.percent)}
                  <div class="info-row" style="font-size:.8rem;">
                    <span class="info-label">Used</span>
                    <span class="info-value">{fmt_bytes(usage.used)} / {fmt_bytes(usage.total)} ({usage.percent:.1f}%)</span>
                  </div>
                </div>
                """, unsafe_allow_html=True)
            except PermissionError:
                pass
    except Exception as e:
        st.warning(f"Failed to retrieve disk info: {e}")

with sysinfo_col:
    import platform
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "N/A"

    st.markdown(f"""
    <div class="info-card">
      <div style="font-size:.9rem;font-weight:700;color:#1a2a4a;margin-bottom:.5rem;">🖥️ Server Info</div>
      <div class="info-row"><span class="info-label">Hostname</span>
        <span class="info-value">{hostname}</span></div>
      <div class="info-row"><span class="info-label">IP Address</span>
        <span class="info-value">{local_ip}</span></div>
      <div class="info-row"><span class="info-label">OS</span>
        <span class="info-value">{platform.system()} {platform.release()}</span></div>
      <div class="info-row"><span class="info-label">Architecture</span>
        <span class="info-value">{platform.machine()}</span></div>
      <div class="info-row"><span class="info-label">Python</span>
        <span class="info-value">{platform.python_version()}</span></div>
      <div class="info-row"><span class="info-label">Streamlit</span>
        <span class="info-value">{st.__version__}</span></div>
      <div class="info-row"><span class="info-label">Uptime</span>
        <span class="info-value">{uptime_str()}</span></div>
    </div>
    """, unsafe_allow_html=True)

# ── Network Interfaces ────────────────────────────────────────────────
st.markdown('<div style="font-size:.9rem;font-weight:700;color:#1a2a4a;margin:.8rem 0 .4rem;">🌐 Network Interfaces</div>', unsafe_allow_html=True)

net_io = psutil.net_io_counters(pernic=True)
net_addrs = psutil.net_if_addrs()
net_stats = psutil.net_if_stats()

iface_cards = []
for iface, addrs in net_addrs.items():
    ipv4 = next((a.address for a in addrs if a.family == socket.AF_INET), None)
    if not ipv4 or iface.startswith("lo"):
        continue
    io = net_io.get(iface)
    stat = net_stats.get(iface)
    speed = f"{stat.speed} Mbps" if stat and stat.speed else "N/A"
    is_up = stat.isup if stat else False
    sent = fmt_bytes(io.bytes_sent) if io else "N/A"
    recv = fmt_bytes(io.bytes_recv) if io else "N/A"
    iface_cards.append((iface, ipv4, speed, is_up, sent, recv))

if iface_cards:
    n_cols = min(3, len(iface_cards))
    iface_cols = st.columns(n_cols)
    for idx, (iface, ipv4, speed, is_up, sent, recv) in enumerate(iface_cards):
        status_dot = "🟢" if is_up else "🔴"
        with iface_cols[idx % n_cols]:
            st.markdown(f"""
            <div class="info-card" style="padding:.65rem .9rem;">
              <div style="font-weight:700;color:#1a2a4a;font-size:.88rem;">
                {status_dot} {iface}
              </div>
              <div class="info-row" style="font-size:.8rem;">
                <span class="info-label">IP</span>
                <span class="info-value">{ipv4}</span></div>
              <div class="info-row" style="font-size:.8rem;">
                <span class="info-label">Speed</span>
                <span class="info-value">{speed}</span></div>
              <div class="info-row" style="font-size:.8rem;">
                <span class="info-label">Sent</span>
                <span class="info-value">{sent}</span></div>
              <div class="info-row" style="font-size:.8rem;">
                <span class="info-label">Received</span>
                <span class="info-value">{recv}</span></div>
            </div>
            """, unsafe_allow_html=True)
else:
    st.info("Failed to retrieve network interface info.")

# ════════════════════════════════════════════════════════════════════
# SECTION 2 — External Connection Status
# ════════════════════════════════════════════════════════════════════

st.markdown('<div class="section-title">🔌 External Connection Status</div>', unsafe_allow_html=True)
st.caption("Connection test results are cached for up to 30 seconds. Refresh the browser to see the latest status.")

conn_col1, conn_col2 = st.columns(2)

# ── Database ─────────────────────────────────────────────────────────
with conn_col1:
    st.markdown("#### 🗄️ Database")

    # MariaDB ES_USER
    mariadb_cfg = load_config("mariadb_es_user.json")
    if mariadb_cfg:
        ok, msg, ms = test_mariadb(mariadb_cfg)
        st.markdown(f"""
        <div class="conn-card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <div class="conn-title">🐬 MariaDB — ES_USER</div>
            {badge(ok)}
          </div>
          <div class="conn-detail">
            Host: <b>{mariadb_cfg.get('host')}:{mariadb_cfg.get('port')}</b> &nbsp;|&nbsp;
            DB: <b>{mariadb_cfg.get('database')}</b> &nbsp;|&nbsp;
            User: <b>{mariadb_cfg.get('user')}</b>
          </div>
          <div class="conn-detail" style="margin-top:.3rem;">
            {'✔ ' if ok else '✖ '}{msg} &nbsp;
            <span style="color:#888;">Response: {ms:.1f} ms</span>
          </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.warning("Failed to read MariaDB config file.")

    # Oracle DB (ABXMES / ESLPPROD) — TCP port check
    for label, cfg_file, user_key in [
        ("Oracle DB — ABXMES",   "oracle_db.json",   "username"),
        ("Oracle DB — ESLPPROD", "eslpprod_db.json",  "user"),
    ]:
        cfg = load_config(cfg_file)
        if cfg:
            ok, msg, ms = test_tcp(cfg["host"], int(cfg["port"]), label)
            srv = cfg.get("service_name", "")
            usr = cfg.get(user_key, "")
            st.markdown(f"""
            <div class="conn-card">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <div class="conn-title">🔶 {label}</div>
                {badge(ok, "Port Open", "Port Closed")}
              </div>
              <div class="conn-detail">
                Host: <b>{cfg.get('host')}:{cfg.get('port')}</b> &nbsp;|&nbsp;
                Service: <b>{srv}</b> &nbsp;|&nbsp; User: <b>{usr}</b>
              </div>
              <div class="conn-detail" style="margin-top:.3rem;">
                {'✔ ' if ok else '✖ '}{msg} &nbsp;
                <span style="color:#888;">Response: {ms:.1f} ms</span>
              </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.warning(f"Failed to read config file for {label}.")

# ── External Services & Internet ──────────────────────────────────────
with conn_col2:
    st.markdown("#### 🌐 External Services & Internet")

    # Vizion API
    vizion_cfg = load_config("vizion_api.json")
    app_url = vizion_cfg.get("app_url", "https://app.vizionapi.com") if vizion_cfg else "https://app.vizionapi.com"
    ok, msg, ms, status_code = test_http(app_url, "Vizion")
    st.markdown(f"""
    <div class="conn-card">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div class="conn-title">🚢 Vizion API</div>
        {badge(ok, f"Reachable ({status_code})", "Unreachable", "Timeout")}
      </div>
      <div class="conn-detail">URL: <b>{app_url}</b></div>
      <div class="conn-detail" style="margin-top:.3rem;">
        {msg} &nbsp;
        <span style="color:#888;">Response: {ms:.1f} ms</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Google Sheets API — TCP port 443 check
    ok_gs, msg_gs, ms_gs = test_tcp("sheets.googleapis.com", 443, "GSheet")
    st.markdown(f"""
    <div class="conn-card">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div class="conn-title">📊 Google Sheets API</div>
        {badge(ok_gs, "Reachable", "Unreachable")}
      </div>
      <div class="conn-detail">Host: <b>sheets.googleapis.com:443</b></div>
      <div class="conn-detail" style="margin-top:.3rem;">
        {'✔ ' if ok_gs else '✖ '}{msg_gs} &nbsp;
        <span style="color:#888;">Response: {ms_gs:.1f} ms</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Internet (Google DNS 8.8.8.8)
    ok_net, msg_net, ms_net = test_tcp("8.8.8.8", 53, "Google DNS")
    st.markdown(f"""
    <div class="conn-card">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div class="conn-title">🌍 Internet (Google DNS)</div>
        {badge(ok_net, "Connected", "No Internet")}
      </div>
      <div class="conn-detail">Host: <b>8.8.8.8:53</b> (TCP DNS)</div>
      <div class="conn-detail" style="margin-top:.3rem;">
        {'✔ ' if ok_net else '✖ '}{msg_net} &nbsp;
        <span style="color:#888;">Response: {ms_net:.1f} ms</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Hankook-AtlasBX Website
    ok_hk, msg_hk, ms_hk, sc_hk = test_http("https://www.hankook-atlasbx.com/", "Hankook")
    st.markdown(f"""
    <div class="conn-card">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div class="conn-title">🏢 Hankook-AtlasBX Website</div>
        {badge(ok_hk, f"Reachable ({sc_hk})", "Unreachable", "Timeout")}
      </div>
      <div class="conn-detail">URL: <b>https://www.hankook-atlasbx.com/</b></div>
      <div class="conn-detail" style="margin-top:.3rem;">
        {msg_hk} &nbsp;
        <span style="color:#888;">Response: {ms_hk:.1f} ms</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════
# SECTION 3 — Overall Status
# ════════════════════════════════════════════════════════════════════

st.markdown('<div class="section-title">📊 Overall Status</div>', unsafe_allow_html=True)

summary_items = [
    ("CPU",        cpu_pct < 90,  f"{cpu_pct:.1f}%"),
    ("Memory",     mem.percent < 90, f"{mem.percent:.1f}%"),
    ("MariaDB",    ok if mariadb_cfg else False, "Connected" if (mariadb_cfg and ok) else "Error"),
    ("Internet",   ok_net, "Connected" if ok_net else "Failed"),
    ("Vizion API", bool(ok),      "OK" if ok else "Failed"),
]

s_cols = st.columns(len(summary_items))
for col, (name, status, val) in zip(s_cols, summary_items):
    color = "#28a745" if status else "#dc3545"
    icon  = "✅" if status else "❌"
    col.markdown(f"""
    <div style="background:#fff;border-radius:10px;padding:.8rem;text-align:center;
                box-shadow:0 2px 8px rgba(0,0,0,.07);border-top:3px solid {color};">
      <div style="font-size:1.4rem;">{icon}</div>
      <div style="font-weight:700;font-size:.85rem;color:#1a2a4a;">{name}</div>
      <div style="font-size:.78rem;color:#666;">{val}</div>
    </div>
    """, unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════
# SECTION 4 — Page Access Log
# ════════════════════════════════════════════════════════════════════

st.markdown('<div class="section-title">📋 Page Access Log</div>', unsafe_allow_html=True)

# ── IP → Name mapping (hardcoded) ────────────────────────────────────
IP_NAME_MAP: dict[str, str] = {
    "127.0.0.1":     "Server (Local)",
    "::1":           "Server (Local IPv6)",
    "10.82.57.21":   "Sehoon Baek",
    # "192.168.1.10":  "John Doe",
    # "192.168.1.20":  "Jane Smith",
}

def resolve_name(ip: str) -> str:
    return IP_NAME_MAP.get(ip, "")


@st.cache_data(ttl=15, show_spinner=False)
def load_access_logs(
    page_filter: str,
    ip_filter: str,
    limit: int,
    date_from: str,
    date_to: str,
) -> "pd.DataFrame | None":
    import pandas as _pd
    cfg = load_config("mariadb_es_user.json")
    if not cfg:
        return None
    try:
        conn = pymysql.connect(
            host=cfg["host"], port=int(cfg["port"]),
            user=cfg["user"], password=cfg["password"],
            database=cfg["database"], connect_timeout=5,
        )
        conditions = ["1=1"]
        params: list = []
        if page_filter and page_filter != "All":
            conditions.append("page = %s")
            params.append(page_filter)
        if ip_filter:
            conditions.append("ip_address LIKE %s")
            params.append(f"%{ip_filter}%")
        if date_from:
            conditions.append("accessed_at >= %s")
            params.append(date_from + " 00:00:00")
        if date_to:
            conditions.append("accessed_at <= %s")
            params.append(date_to + " 23:59:59")
        where = " AND ".join(conditions)
        sql = f"""
            SELECT id, page, ip_address, accessed_at,
                   LEFT(url, 120) AS url,
                   LEFT(user_agent, 80) AS user_agent
            FROM page_access_log
            WHERE {where}
            ORDER BY accessed_at DESC
            LIMIT %s
        """
        params.append(limit)
        df = _pd.read_sql(sql, conn, params=params)
        conn.close()
        return df
    except pymysql.err.ProgrammingError:
        # Table not yet created (no visits recorded)
        return _pd.DataFrame()
    except Exception:
        return None


@st.cache_data(ttl=15, show_spinner=False)
def load_access_summary() -> "pd.DataFrame | None":
    import pandas as _pd
    cfg = load_config("mariadb_es_user.json")
    if not cfg:
        return None
    try:
        conn = pymysql.connect(
            host=cfg["host"], port=int(cfg["port"]),
            user=cfg["user"], password=cfg["password"],
            database=cfg["database"], connect_timeout=5,
        )
        sql = """
            SELECT
                page,
                COUNT(*)                                    AS total_visits,
                COUNT(DISTINCT ip_address)                  AS unique_ips,
                MAX(accessed_at)                            AS last_visit,
                MIN(accessed_at)                            AS first_visit
            FROM page_access_log
            GROUP BY page
            ORDER BY total_visits DESC
        """
        df = _pd.read_sql(sql, conn)
        conn.close()
        return df
    except Exception:
        return None


@st.cache_data(ttl=15, show_spinner=False)
def load_ip_summary() -> "pd.DataFrame | None":
    import pandas as _pd
    cfg = load_config("mariadb_es_user.json")
    if not cfg:
        return None
    try:
        conn = pymysql.connect(
            host=cfg["host"], port=int(cfg["port"]),
            user=cfg["user"], password=cfg["password"],
            database=cfg["database"], connect_timeout=5,
        )
        sql = """
            SELECT
                ip_address,
                COUNT(*)                                    AS total_visits,
                COUNT(DISTINCT page)                        AS page_count,
                GROUP_CONCAT(DISTINCT page ORDER BY page SEPARATOR ', ') AS pages_visited,
                MAX(accessed_at)                            AS last_visit
            FROM page_access_log
            GROUP BY ip_address
            ORDER BY total_visits DESC
            LIMIT 50
        """
        df = _pd.read_sql(sql, conn)
        conn.close()
        return df
    except Exception:
        return None


import pandas as pd

log_tab, page_tab, ip_tab = st.tabs(["📝 Access Log", "📄 Page Stats", "🌐 IP Stats"])

# ── Tab 1: Access Log ─────────────────────────────────────────────────
with log_tab:
    filter_col1, filter_col2, filter_col3, filter_col4, filter_col5 = st.columns([2, 2, 2, 2, 1])

    with filter_col1:
        page_options = ["All", "Home (Dashboard)", "Forecast Planner",
                        "Master: Material & Customer", "Sales Person Information",
                        "Data to MariaDB", "System Monitor"]
        sel_page = st.selectbox("Page Filter", page_options, key="log_page")

    with filter_col2:
        sel_ip = st.text_input("IP Filter (partial match)", placeholder="e.g. 192.168", key="log_ip")

    with filter_col3:
        from datetime import date as _date, timedelta as _td
        sel_from = st.date_input("From", value=_date.today() - _td(days=7), key="log_from")

    with filter_col4:
        sel_to = st.date_input("To", value=_date.today(), key="log_to")

    with filter_col5:
        sel_limit = st.selectbox("Max Rows", [50, 100, 200, 500], key="log_limit")

    if st.button("🔍 Search", key="log_search"):
        st.cache_data.clear()

    log_df = load_access_logs(
        sel_page, sel_ip,
        int(sel_limit),
        str(sel_from), str(sel_to),
    )

    if log_df is None:
        st.error("Failed to load access log. Check MariaDB connection.")
    elif log_df.empty:
        st.info("No access records found. Records will appear after pages are visited.")
    else:
        st.caption(f"Showing **{len(log_df):,}** records")
        log_df.insert(
            log_df.columns.get_loc("ip_address") + 1,
            "user",
            log_df["ip_address"].map(resolve_name),
        )
        st.dataframe(
            log_df.rename(columns={
                "id": "ID", "page": "Page", "ip_address": "IP Address",
                "user": "User", "accessed_at": "Accessed At",
                "url": "URL", "user_agent": "User-Agent",
            }),
            use_container_width=True,
            hide_index=True,
            column_config={
                "IP Address":  st.column_config.TextColumn("IP Address",  width="small"),
                "User":        st.column_config.TextColumn("User",        width="small"),
                "Accessed At": st.column_config.DatetimeColumn("Accessed At", format="YYYY-MM-DD HH:mm:ss"),
                "URL":         st.column_config.TextColumn("URL",         width="medium"),
                "User-Agent":  st.column_config.TextColumn("User-Agent",  width="medium"),
            },
        )
        csv = log_df.to_csv(index=False, encoding="utf-8-sig")
        st.download_button(
            "📥 Download CSV", csv,
            file_name=f"access_log_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )

# ── Tab 2: Page Stats ─────────────────────────────────────────────────
with page_tab:
    page_stat_df = load_access_summary()
    if page_stat_df is None or (hasattr(page_stat_df, "empty") and page_stat_df.empty):
        st.info("No access records yet.")
    else:
        st.dataframe(
            page_stat_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "last_visit":  st.column_config.DatetimeColumn("Last Visit",  format="YYYY-MM-DD HH:mm:ss"),
                "first_visit": st.column_config.DatetimeColumn("First Visit", format="YYYY-MM-DD HH:mm:ss"),
            },
        )
        if not page_stat_df.empty:
            import plotly.express as _px
            fig_page = _px.bar(
                page_stat_df, x="page", y="total_visits",
                color="total_visits", color_continuous_scale="Blues",
                labels={"page": "Page", "total_visits": "Visits"},
                title="Total Visits by Page",
            )
            fig_page.update_layout(
                margin=dict(l=10, r=10, t=50, b=10),
                height=320, showlegend=False,
                coloraxis_showscale=False,
            )
            st.plotly_chart(fig_page, use_container_width=True)

# ── Tab 3: IP Stats ───────────────────────────────────────────────────
with ip_tab:
    ip_stat_df = load_ip_summary()
    if ip_stat_df is None or (hasattr(ip_stat_df, "empty") and ip_stat_df.empty):
        st.info("No access records yet.")
    else:
        ip_stat_df.insert(
            ip_stat_df.columns.get_loc("ip_address") + 1,
            "user",
            ip_stat_df["ip_address"].map(resolve_name),
        )
        st.dataframe(
            ip_stat_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "ip_address":    st.column_config.TextColumn("IP Address",     width="small"),
                "user":          st.column_config.TextColumn("User",           width="small"),
                "last_visit":    st.column_config.DatetimeColumn("Last Visit", format="YYYY-MM-DD HH:mm:ss"),
                "pages_visited": st.column_config.TextColumn("Pages Visited",  width="large"),
            },
        )
        if not ip_stat_df.empty:
            import plotly.express as _px
            top_ips = ip_stat_df.head(15).copy()
            top_ips["label"] = top_ips.apply(
                lambda r: f"{r['ip_address']} ({r['user']})" if r["user"] else r["ip_address"],
                axis=1,
            )
            fig_ip = _px.bar(
                top_ips, x="label", y="total_visits",
                color="total_visits", color_continuous_scale="Oranges",
                labels={"label": "IP Address", "total_visits": "Visits"},
                title="Total Visits by IP (Top 15)",
            )
            fig_ip.update_layout(
                margin=dict(l=10, r=10, t=50, b=10),
                height=320, showlegend=False,
                coloraxis_showscale=False,
                xaxis_tickangle=0,
            )
            st.plotly_chart(fig_ip, use_container_width=True)

# ── Footer ────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    "<div style='text-align:center;color:#aaa;font-size:.78rem;padding:10px;'>"
    "© 2026 Hankook &amp; Company ES America Corp. &nbsp;|&nbsp; System Monitor"
    "</div>",
    unsafe_allow_html=True,
)
