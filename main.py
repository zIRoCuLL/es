import os
import sys
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from PIL import Image
from datetime import datetime

_BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_BASE_DIR))
from utils.access_logger import log_access

# 환경 설정
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"

# 페이지 설정
st.set_page_config(
    page_title="Hankook & Company ES",
    layout="wide",
    initial_sidebar_state="expanded",
    page_icon="🏠"
)
log_access("Home (Dashboard)")

st.markdown("""
<style>
</style>
""", unsafe_allow_html=True)

# Default values (previously in sidebar)
data_path = "/home/habx/project/es/excel_files"
use_date_filter = False
chart_type = "Bar (막대)"
show_values = True

# 메인 타이틀
st.title("🏢 Hankook & Company ES America Corp.")
st.markdown("### Battery Distribution & Inventory Management Dashboard")
st.markdown("---")

# 1. 데이터 로드 및 병합 (캐싱 처리로 성능 최적화)
@st.cache_data
def load_and_merge_data(data_path):
    """데이터를 로드하고 병합하는 함수"""
    try:
        # 파일 경로 설정
        sap_file = os.path.join(data_path, "sap.xlsx")
        inv_file = os.path.join(data_path, "inventory.xlsx")
        
        # 파일 존재 확인
        if not os.path.exists(sap_file):
            st.error(f"❌ SAP 파일을 찾을 수 없습니다: {sap_file}")
            return None
        
        if not os.path.exists(inv_file):
            st.error(f"❌ Inventory 파일을 찾을 수 없습니다: {inv_file}")
            return None
        
        # 데이터 불러오기
        with st.spinner("📂 데이터를 불러오는 중..."):
            sap_df = pd.read_excel(sap_file)
            inv_df = pd.read_excel(inv_file)
        
        # 병합 기준 컬럼 확인
        if 'mat. no' not in sap_df.columns:
            # 유사한 컬럼명 찾기
            mat_col = [col for col in sap_df.columns if 'mat' in col.lower() and 'no' in col.lower()]
            if mat_col:
                sap_df['mat. no'] = sap_df[mat_col[0]]
            else:
                st.error("❌ SAP 파일에서 'mat. no' 컬럼을 찾을 수 없습니다.")
                return None
        
        if 'Product No' not in inv_df.columns:
            # 유사한 컬럼명 찾기
            prod_col = [col for col in inv_df.columns if 'product' in col.lower() and 'no' in col.lower()]
            if prod_col:
                inv_df['Product No'] = inv_df[prod_col[0]]
            else:
                st.error("❌ Inventory 파일에서 'Product No' 컬럼을 찾을 수 없습니다.")
                return None
        
        # 병합 기준 컬럼 전처리 (10자리 문자열 일치)
        sap_df['merge_key'] = sap_df['mat. no'].astype(str).str.strip().str[:10]
        inv_df['merge_key'] = inv_df['Product No'].astype(str).str.strip().str[:10]
        
        # 중복 컬럼 확인 및 제거
        common_cols = list(set(sap_df.columns) & set(inv_df.columns))
        common_cols.remove('merge_key')  # merge_key는 유지
        
        # inventory에서 중복 컬럼 제거
        inv_df_unique = inv_df.drop(columns=[col for col in common_cols if col in inv_df.columns])
        
        # 데이터 병합
        with st.spinner("🔄 데이터를 병합하는 중..."):
            merged_df = pd.merge(
                sap_df, 
                inv_df_unique, 
                on='merge_key',
                how='left',
                suffixes=('', '_inv')
            )
        
        # 중복 제거 (merge_key 기준)
        merged_df = merged_df.drop_duplicates(subset=['merge_key'], keep='first')
        
        return merged_df, sap_df, inv_df
    
    except Exception as e:
        st.error(f"❌ 데이터 로드 중 오류 발생: {str(e)}")
        return None

# 2. 월별 데이터 집계 함수
@st.cache_data
def aggregate_monthly_data(merged_df):
    """월별 데이터를 집계하는 함수"""
    try:
        # 날짜 컬럼 확인
        date_col = None
        for col in merged_df.columns:
            if 'delivery' in col.lower() and 'date' in col.lower():
                date_col = col
                break
        
        if date_col is None:
            st.warning("⚠️ 날짜 컬럼을 찾을 수 없습니다. 'delivery request date' 컬럼을 확인하세요.")
            return None
        
        # 날짜 처리
        merged_df[date_col] = pd.to_datetime(merged_df[date_col], errors='coerce')
        
        # 유효한 날짜만 필터링
        valid_dates_df = merged_df[merged_df[date_col].notna()].copy()
        
        if len(valid_dates_df) == 0:
            st.warning("⚠️ 유효한 날짜 데이터가 없습니다.")
            return None
        
        # 월별 집계
        monthly_df = valid_dates_df.set_index(date_col).resample('M').agg({
            'order q.ty': 'sum' if 'order q.ty' in valid_dates_df.columns else lambda x: 0,
            'Quantity': 'sum' if 'Quantity' in valid_dates_df.columns else lambda x: 0
        }).reset_index()
        
        monthly_df['Month'] = monthly_df[date_col].dt.strftime('%Y-%m')
        
        return monthly_df
    
    except Exception as e:
        st.error(f"❌ 월별 집계 중 오류 발생: {str(e)}")
        return None

# 3. 차트 생성 함수
def create_chart(df, chart_type, show_values):
    """Plotly 차트를 생성하는 함수"""
    fig = go.Figure()
    
    if chart_type == "Bar (막대)":
        # Order Qty 막대
        fig.add_trace(go.Bar(
            x=df['Month'],
            y=df['order q.ty'],
            name='Order Qty',
            marker_color='#003366',
            text=df['order q.ty'].apply(lambda x: f"{x:,.0f}") if show_values else None,
            textposition='outside' if show_values else None
        ))
        
        # Quantity 막대
        fig.add_trace(go.Bar(
            x=df['Month'],
            y=df['Quantity'],
            name='Stock Quantity',
            marker_color='#FF5000',
            text=df['Quantity'].apply(lambda x: f"{x:,.0f}") if show_values else None,
            textposition='outside' if show_values else None
        ))
        
        fig.update_layout(barmode='group')
    
    elif chart_type == "Line (선)":
        # Order Qty 선
        fig.add_trace(go.Scatter(
            x=df['Month'],
            y=df['order q.ty'],
            name='Order Qty',
            mode='lines+markers',
            line=dict(color='#003366', width=3),
            marker=dict(size=8)
        ))
        
        # Quantity 선
        fig.add_trace(go.Scatter(
            x=df['Month'],
            y=df['Quantity'],
            name='Stock Quantity',
            mode='lines+markers',
            line=dict(color='#FF5000', width=3),
            marker=dict(size=8)
        ))
    
    else:  # Bar + Line (복합)
        # Order Qty 막대
        fig.add_trace(go.Bar(
            x=df['Month'],
            y=df['order q.ty'],
            name='Order Qty',
            marker_color='#003366',
            yaxis='y',
            text=df['order q.ty'].ro.apply(lambda x: f"{x:,.0f}") if show_values else None,
            textposition='outside' if show_values else None
        ))
        
        # Quantity 선
        fig.add_trace(go.Scatter(
            x=df['Month'],
            y=df['Quantity'],
            name='Stock Quantity',
            mode='lines+markers',
            line=dict(color='#FF5000', width=3),
            marker=dict(size=10),
            yaxis='y2'
        ))
        
        # 이중 축 설정
        fig.update_layout(
            yaxis=dict(title="Order Qty"),
            yaxis2=dict(title="Stock Quantity", overlaying='y', side='right')
        )
    
    # 레이아웃 설정
    fig.update_layout(
        title='Monthly Order vs Inventory Quantity',
        xaxis_tickangle=-45,
        xaxis_title="Month",
        yaxis_title="Quantity",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        hovermode='x unified',
        margin=dict(l=20, r=20, t=80, b=20),
        height=500
    )
    
    return fig

# 메인 로직
try:
    # 데이터 로드
    result = load_and_merge_data(data_path)
    
    if result is not None:
        merged_df, sap_df, inv_df = result
        
        # 날짜 필터 적용
        if use_date_filter:
            date_col = None
            for col in merged_df.columns:
                if 'delivery' in col.lower() and 'date' in col.lower():
                    date_col = col
                    break
            
            if date_col:
                merged_df[date_col] = pd.to_datetime(merged_df[date_col], errors='coerce')
                mask = (merged_df[date_col] >= pd.to_datetime(start_date)) & \
                       (merged_df[date_col] <= pd.to_datetime(end_date))
                merged_df = merged_df[mask]
        
        # 월별 집계
        monthly_df = aggregate_monthly_data(merged_df)
        
        if monthly_df is not None and len(monthly_df) > 0:
            # 화면 레이아웃 배치
            col1, col2 = st.columns([1, 1])
            
            with col1:
                # 이미지 표시
                image_path = "/home/habx/project/es/pic/img_ac_intro.jpg"
                if os.path.exists(image_path):
                    st.image(image_path, caption="Hankook & Company ES", use_container_width=True)
                else:
                    st.info("📷 이미지 파일을 찾을 수 없습니다: " + image_path)
                
                st.markdown("""
                ### 🌐 Quick Links
                - [Hankook & Company ES America Corp.](https://www.hankook-atlasbx.com/)
                - [제품 정보](https://www.hankook-atlasbx.com/products)
                """)
                
                # 요약 통계
                st.subheader("📈 주요 통계")
                stat_col1, stat_col2, stat_col3 = st.columns(3)
                
                with stat_col1:
                    total_orders = merged_df['order q.ty'].sum() if 'order q.ty' in merged_df.columns else 0
                    st.metric("총 주문량", f"{total_orders:,.0f}")
                
                with stat_col2:
                    total_inventory = merged_df['Quantity'].sum() if 'Quantity' in merged_df.columns else 0
                    st.metric("총 재고량", f"{total_inventory:,.0f}")
                
                with stat_col3:
                    unique_products = merged_df['merge_key'].nunique()
                    st.metric("제품 종류", f"{unique_products:,}")
            
            with col2:
                st.subheader("📊 Monthly Statistics")
                fig = create_chart(monthly_df, chart_type, show_values)
                st.plotly_chart(fig, use_container_width=True)
            
            # 데이터 테이블
            st.markdown("---")
            st.subheader("📋 월별 상세 데이터")
            
            # 데이터 포맷팅
            display_df = monthly_df.copy()
            display_df['order q.ty'] = display_df['order q.ty'].round(0).astype(int)
            display_df['Quantity'] = display_df['Quantity'].round(0).astype(int)
            
            st.dataframe(
                display_df[['Month', 'order q.ty', 'Quantity']],
                use_container_width=True,
                hide_index=True
            )
            
            # 다운로드 버튼
            csv = display_df.to_csv(index=False, encoding='utf-8-sig')
            st.download_button(
                label="📥 CSV 다운로드",
                data=csv,
                file_name=f"monthly_statistics_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
        else:
            st.warning("⚠️ 집계할 데이터가 없습니다.")
    else:
        st.error("❌ 데이터를 불러올 수 없습니다. 파일 경로와 파일명을 확인하세요.")

except Exception as e:
    st.error(f"❌ 처리 중 오류가 발생했습니다: {str(e)}")
    st.exception(e)

st.markdown("---")
st.markdown(
    "<div style='text-align:center;color:#aaa;font-size:.78rem;padding:10px;'>"
    "© 2026 Hankook & Company ES America Corp. &nbsp;|&nbsp; Home"
    "</div>",
    unsafe_allow_html=True,
)
