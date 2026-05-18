"""
접속 이력 로거 — 각 Streamlit 페이지에서 호출
Usage:
    from utils.access_logger import log_access
    log_access("페이지명")
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pymysql
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent.parent
_CONFIG_PATH = BASE_DIR / "info_config" / "mariadb_es_user.json"

# 테이블 DDL
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS page_access_log (
    id          BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    page        VARCHAR(120) NOT NULL COMMENT '페이지 이름',
    ip_address  VARCHAR(60)  NOT NULL COMMENT '접속 IP',
    url         TEXT                  COMMENT '접속 URL',
    user_agent  TEXT                  COMMENT 'User-Agent',
    accessed_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '접속 시각',
    INDEX idx_page        (page),
    INDEX idx_ip          (ip_address),
    INDEX idx_accessed_at (accessed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='페이지 접속 이력';
"""


def _get_conn() -> pymysql.connections.Connection:
    cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    return pymysql.connect(
        host=cfg["host"],
        port=int(cfg["port"]),
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        connect_timeout=5,
        autocommit=True,
    )


def _ensure_table(conn: pymysql.connections.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(_CREATE_TABLE_SQL)


def _get_client_ip() -> str:
    try:
        headers = st.context.headers
        # 리버스 프록시(nginx 등)가 있는 경우 실제 클라이언트 IP를 헤더에서 추출
        for header in ("x-forwarded-for", "x-real-ip"):
            val = headers.get(header, "")
            if val:
                # X-Forwarded-For: client, proxy1, proxy2 → 첫 번째가 실제 IP
                return val.split(",")[0].strip()
        # 직접 접속 IP (localhost는 None 반환 → 127.0.0.1로 표기)
        ip = st.context.ip_address
        return str(ip) if ip else "127.0.0.1"
    except Exception:
        return "unknown"


def _get_url() -> str:
    try:
        return str(st.context.url) if st.context.url else ""
    except Exception:
        return ""


def _get_user_agent() -> str:
    try:
        headers = st.context.headers
        return headers.get("user-agent", "") or headers.get("User-Agent", "")
    except Exception:
        return ""


def log_access(page: str) -> None:
    """
    현재 접속자의 IP / URL / User-Agent 를 MariaDB 에 기록합니다.
    세션당 1회만 저장 (중복 방지).
    """
    session_key = f"_access_logged_{page}"
    if st.session_state.get(session_key):
        return

    try:
        ip = _get_client_ip()
        url = _get_url()
        ua  = _get_user_agent()
        now = datetime.now()

        conn = _get_conn()
        _ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO page_access_log (page, ip_address, url, user_agent, accessed_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (page, ip, url, ua, now),
            )
        conn.close()

        st.session_state[session_key] = True

    except Exception as e:
        # 로그 실패는 조용히 무시 (페이지 동작에 영향 없도록)
        pass
