import streamlit as st
import pandas as pd
import numpy as np
import json
import time, os, re, threading
import sqlite3
import plotly.express as px
from datetime import datetime, date, timedelta
from io import StringIO
from typing import Optional
import streamlit.components.v1 as components
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

try:
    import asyncio.proactor_events
    
    def silence_proactor_bug(func):
        # 💡 [핵심 보완] 문제가 되는 @wraps(func)를 과감히 제거했습니다.
        # 기능은 완전히 동일하면서 파이썬 버전에 따른 import 오류를 원천 차단합니다.
        def wrapper(*args, **kwargs):
            try:
                if func:
                    return func(*args, **kwargs)
            except (OSError, ValueError):
                # OSError: [WinError 10038] 소켓이 아닙니다 에러 등을 조용히 무시
                pass
        return wrapper

    # 윈도우 프로액터 연결 유실 시 발생하는 버그 함수를 안전하게 감싸서 차단합니다.
    if hasattr(asyncio.proactor_events, '_ProactorBasePipeTransport'):
        tp = asyncio.proactor_events._ProactorBasePipeTransport
        if hasattr(tp, '_call_connection_lost'):
            # 기존 함수가 정상적일 때만 덮어씌우도록 안전장치 보완
            original_func = getattr(tp, '_call_connection_lost', None)
            if original_func:
                tp._call_connection_lost = silence_proactor_bug(original_func)
            
except (ImportError, AttributeError, Exception):
    # 만약 OS 환경이 다르거나 에러가 날 경우 대시보드 구동을 방해하지 않고 통과
    pass

# ══════════════════════════════════════════════════
# [SECTION 0] SYSTEM PATH & CONFIGURATION (DB 분리 반영)
# ══════════════════════════════════════════════════
ARGO_DIR        = r"C:\Akros\Argo"
BASE_DIR        = r"C:\akros"
LIVE_SCAN_PATH  = r"C:\akros\live_scan.json"
LIVE_SCAN_KR_PATH  = r"C:\akros\live_scan_kr.json"
REFRESH_SEC     = 5

# 분리된 DB 파일 경로
DB_GLOBAL       = os.path.join(ARGO_DIR, "akros_global.db")      # 해외 매매
DB_KR           = os.path.join(ARGO_DIR, "akros_kr.db")          # 국내 매매
DB_KR_DATA      = os.path.join(ARGO_DIR, "akros_kr_data.db")     # 키움 수집 (투자자 동향 등)
DB_MACRO        = os.path.join(ARGO_DIR, "akros_macro.db")       # 거시지표 (argo_macro)
DB_NEWS         = os.path.join(ARGO_DIR, "akros_news.db")        # 뉴스 (global_intelligence)
DB_ANALYSIS     = os.path.join(ARGO_DIR, "akros_analysis.db")    # 분석 결과 (선택)

os.makedirs(ARGO_DIR, exist_ok=True)

# ══════════════════════════════════════════════════
# [SECTION 1] CAPITAL & RISK PARAMETERS (변경 없음)
# ══════════════════════════════════════════════════
SEED_CAPITAL   = 100_000.0
POS_STOCK_COIN = 1_000.0
FUT_CONTRACTS  = 3

STOCK_COMMISSION_PER_SHARE = 0.005
STOCK_MIN_COMMISSION       = 1.00
COIN_COMMISSION_RATE       = 0.0018
FUTURE_COMMISSION_PER_CONTRACT_SIDE = 0.85

CONTRACT_MULTIPLIERS = {
    'ES': 50, 'MES': 5,
    'NQ': 20, 'MNQ': 2,
    'HG': 25000, 'NG': 10000,
    'GC': 100,  'SI': 5000,
    'CL': 1000, 'ZN': 1000,
    'ZB': 1000, 'ZF': 1000,
    '6E': 125000, '6J': 12500000,
    '6C': 100000,
}

TRADING_START_HOUR  = 6
TRADING_END_HOUR    = 5
NO_ENTRY_AFTER_HOUR = 5
STOCK_ENTRY_START_HOUR   = 22
STOCK_ENTRY_START_MINUTE = 31
STOCK_ENTRY_END_HOUR     = 5

CLOSE_EVTS = [
    'TP1_30PCT', 'TP2_40PCT', 'TP3_30PCT',
    'TP1_50PCT', 'TP2_30PCT', 'TP3_20PCT',
    'TP2_50PCT',
    'TP3_TREND_END',
    'STOP_LOSS',
    'PHASE1_EXIT', 'PHASE2_EXIT',
    'SEC_EXIT', 'SLOPE_EXIT',
    'PUL_EXIT', 'BREAKEVEN_CUT',
    'EOD_FORCE_CLOSE', 'FORCE_CLOSE',
    'PRE_EVENT_EXIT',
    'SHORT_IMMED_EXIT', 'SHORT_LOSS_EJECT',
]
ENTRY_EVTS = {'ENTRY', 'GITMO_ENTRY'}
PARTIAL_EXIT_RATIOS = {
    'TP1_30PCT': 0.30,
    'TP2_40PCT': 0.40,
    'TP1_50PCT': 0.50,
    'TP2_30PCT': 0.30,
    'TP2_50PCT': 0.50,
}
FINAL_EXIT_EVTS = set(CLOSE_EVTS) - set(PARTIAL_EXIT_RATIOS)

# ══════════════════════════════════════════════════
# [SECTION 2] PAGE CONFIG & CSS (변경 없음, 생략)
# ══════════════════════════════════════════════════
st.set_page_config(page_title="AKROS CORPORATE STRATEGY OFFICE", layout="wide", page_icon="🛡️")

st.markdown("""
<style>
/* 기존 CSS 그대로 - 생략 (길이 문제로 실제 파일에는 전체 포함) */
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@700;900&family=Rajdhani:wght@500;700&display=swap');
html,body,[class*="css"]{font-family:'Rajdhani',sans-serif;background:#0a0e1a;color:#c8d8e8;}
.stApp{background:#0a0e1a;}
h1{font-family:'Orbitron',sans-serif !important;color:#00e5ff !important;
   letter-spacing:6px;font-size:1.6rem !important;font-weight:900 !important;
   margin-top:0 !important;margin-bottom:10px !important;
   text-shadow:0 0 18px rgba(0,229,255,0.55),0 0 36px rgba(0,229,255,0.25);}
section[data-testid="stAppViewContainer"]>div:first-child{padding-top:0 !important;}
header[data-testid="stHeader"]{height:0;min-height:0;}
div[data-testid="stToolbar"]{display:none;}
.block-container{padding-top:0 !important;padding-bottom:0 !important;}
h2,h3,h4,h5{color:#7ecfff !important;font-weight:600 !important;letter-spacing:2px;}
.sbar{background:#0d1829;border:1px solid #1a2e45;border-radius:4px;padding:5px 14px;
  font-family:'Share Tech Mono',monospace;font-size:0.67rem;color:#5a7a9a;
  display:flex;gap:16px;margin-bottom:12px;flex-wrap:wrap;}
.ph{border-left:3px solid #00e5ff;background:linear-gradient(90deg,#0d2137,#0a0e1a);
  padding:7px 16px;margin:14px 0 8px;font-family:'Share Tech Mono',monospace;
  font-size:0.8rem;color:#00e5ff;letter-spacing:3px;}
.ph.today{border-left-color:#ffe066;color:#ffe066;}
.ph.p2{border-left-color:#00e676;color:#00e676;}
.kpi{background:#0d1829;border:1px solid #1a2e45;border-radius:6px;
  padding:14px 16px;text-align:center;position:relative;overflow:hidden;}
.kpi::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;}
.kpi.c1::before{background:#00e5ff;}.kpi.c2::before{background:#00e676;}
.kpi.c3::before{background:#ff4444;}.kpi.c4::before{background:#ffe066;}
.kpi.c5::before{background:#b388ff;}.kpi.c6::before{background:#ffa726;}
.kpi-lbl{font-family:'Rajdhani',sans-serif;font-size:0.78rem;color:#a5c7e9;
  letter-spacing:0px;margin-bottom:6px;font-weight:800;display:block;text-align:center;}
.kpi-val{font-family:'Share Tech Mono',monospace;font-size:1.65rem;font-weight:700;
  line-height:1.1;display:block;text-align:center;}
.kpi-val.c1{color:#00e5ff;}.kpi-val.c2{color:#00e676;}.kpi-val.c3{color:#ff4444;}
.kpi-val.c4{color:#ffe066;}.kpi-val.c5{color:#b388ff;}.kpi-val.c6{color:#ffa726;}
.kpi-sub{font-family:'Rajdhani',sans-serif;font-size:0.67rem;color:#3a5a7a;
  margin-top:3px;font-weight:500;display:block;text-align:center;}
.scroll-box{background:#080d18;border:1px solid #1a2e45;border-radius:6px;
  height:340px;overflow-y:auto;padding:6px 0;}
.hit-row{padding:7px 12px;border-bottom:1px solid #0d1829;
  font-family:'Share Tech Mono',monospace;font-size:0.75rem;line-height:1.5;}
.hit-row:hover{background:#0d1829;}
.hl{border-left:3px solid #ff4444;}.hs{border-left:3px solid #1C83E1;}
.sl{color:#ff4444;font-weight:700;}.ss{color:#1C83E1;font-weight:700;}
.hp{color:#c8d8e8;}.gA{color:#ffe066;}.gB{color:#7ecfff;}.gC{color:#5a7a9a;}
.ht{color:#3a5a7a;font-size:0.67rem;}
.ppos{color:#00e676;font-weight:700;}.pneg{color:#ff4444;font-weight:700;}
.pneu{color:#7ecfff;font-weight:700;}
.boxtitle{font-family:'Share Tech Mono',monospace;font-size:0.72rem;
  color:#5a7a9a;letter-spacing:2px;padding:0 4px;margin-bottom:4px;}
.asset-bar{display:flex;justify-content:space-between;align-items:stretch;
  margin-bottom:14px;gap:8px;font-family:'Share Tech Mono',monospace;}
.asset-cell{flex:1;min-width:0;background:#0d1829;border:1px solid #1a2e45;
  border-radius:6px;padding:14px 12px;text-align:center;
  position:relative;overflow:hidden;}
.asset-cell::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;}
.asset-cell:nth-child(1)::before{background:#00e5ff;}
.asset-cell:nth-child(2)::before{background:#00e676;}
.asset-cell:nth-child(3)::before{background:#ffe066;}
.asset-cell:nth-child(4)::before{background:#b388ff;}
.asset-cell:nth-child(5)::before{background:#ffa726;}
.asset-cell:nth-child(6)::before{background:#ff6b9d;}
.asset-lbl{font-size:0.64rem;font-weight:800;color:#a5c7e9;letter-spacing:1px;
  text-transform:uppercase;margin-bottom:8px;white-space:normal;line-height:1.3;
  min-height:2.2em;display:block;font-family:'Rajdhani',sans-serif;}
.asset-val{font-size:1.15rem;font-weight:800;letter-spacing:1px;line-height:1.1;display:block;}
.asset-sub{font-size:0.68rem;font-weight:500;margin-top:5px;display:block;color:#3a5a7a;}
.av-total{color:#00e5ff;}
.av-profit{color:#00e676;}
.av-loss{color:#ff4444;}
.av-neutral{color:#c8d8e8;}
.time-banner{border-radius:4px;padding:8px 16px;margin-bottom:8px;
  font-family:'Share Tech Mono',monospace;font-size:0.78rem;text-align:center;
  letter-spacing:2px;border:1px solid;}
.time-banner.ok{background:#0a1a0a;border-color:#00e676;color:#00e676;}
.time-banner.warning{background:#1a1a0a;border-color:#ffa726;color:#ffa726;
  animation:pulse-warn 1.5s infinite;}
.time-banner.danger{background:#1a0a0a;border-color:#ff4444;color:#ff4444;
  animation:pulse-danger 1s infinite;}
.time-banner.closed{background:#0a0a1a;border-color:#5a7a9a;color:#5a7a9a;}
.time-banner-row{display:flex;gap:8px;margin-bottom:12px;}
.time-banner-row .time-banner{flex:1;margin-bottom:0;}
@keyframes pulse-warn{0%,100%{opacity:1;}50%{opacity:0.6;}}
@keyframes pulse-danger{0%,100%{opacity:1;}50%{opacity:0.5;}}
@keyframes pulse-scan{0%,100%{opacity:1;border-color:#00e5ff;}50%{opacity:0.7;border-color:#00e676;}}
.violation-box{background:#1a0a0a;border:2px solid #ff4444;border-radius:6px;
  padding:12px 16px;margin:10px 0;font-family:'Share Tech Mono',monospace;}
.violation-title{color:#ff4444;font-size:0.85rem;font-weight:700;margin-bottom:8px;letter-spacing:2px;}
.violation-item{color:#ffa726;font-size:0.72rem;padding:4px 0;border-bottom:1px solid #2a1a1a;}
.violation-item:last-child{border-bottom:none;}
.violation-reason{color:#ff6666;font-size:0.65rem;margin-left:8px;}
.scan-banner{border-radius:4px;padding:8px 16px;margin-top:10px;margin-bottom:8px;
  font-family:'Share Tech Mono',monospace;font-size:0.78rem;text-align:center;
  letter-spacing:2px;border:1px solid;}
.scan-banner.running{background:#0a0a1a;border-color:#00e5ff;color:#00e5ff;
  animation:pulse-scan 2s infinite;}
.scan-banner.idle{background:#0a0a1a;border-color:#2a3a4a;color:#3a5a7a;}
.scan-progress{color:#00e676;font-weight:700;}
.scan-symbol{color:#ffe066;font-weight:700;}
.mi-ph{border-left:3px solid #b388ff;background:linear-gradient(90deg,#120d1f,#0a0e1a);
  padding:7px 16px;margin:20px 0 12px;font-family:'Orbitron',sans-serif;
  font-size:0.8rem;color:#b388ff;letter-spacing:3px;
  text-shadow:0 0 10px rgba(179,136,255,0.7),0 0 24px rgba(179,136,255,0.3);}
.mi-cards{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;}
.mi-card{flex:1;min-width:130px;background:#0d1829;border:1px solid #1a2e45;
  border-radius:6px;padding:12px 14px;text-align:center;position:relative;overflow:hidden;}
.mi-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;}
.mi-c-pur::before{background:#b388ff;}.mi-c-red::before{background:#ff4444;}
.mi-c-grn::before{background:#00e676;}.mi-c-yel::before{background:#ffe066;}
.mi-lbl{font-family:'Rajdhani',sans-serif;font-size:0.66rem;color:#7a9aba;
  letter-spacing:0.5px;margin-bottom:6px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.mi-val{font-family:'Share Tech Mono',monospace;font-size:1.25rem;font-weight:700;line-height:1.1;white-space:nowrap;letter-spacing:0;}
.mi-c-pur .mi-val{color:#b388ff;}.mi-c-red .mi-val{color:#ff4444;}
.mi-c-grn .mi-val{color:#00e676;}.mi-c-yel .mi-val{color:#ffe066;}
.mi-cls{font-size:0.62rem;color:#3a5a7a;margin-top:4px;
  font-family:'Rajdhani',sans-serif;font-weight:600;}
.chart-section-label{font-family:'Orbitron',sans-serif;font-size:0.75rem;
  color:#b388ff;letter-spacing:2px;margin:16px 0 6px;font-weight:700;
  text-shadow:0 0 10px rgba(179,136,255,0.7),0 0 24px rgba(179,136,255,0.3);}
.gb-ph{border-left:3px solid #b388ff;background:linear-gradient(90deg,#120d1f,#0a0e1a);
  padding:7px 16px;margin:20px 0 12px;font-family:'Orbitron',sans-serif;
  font-size:0.8rem;color:#b388ff;letter-spacing:3px;
  text-shadow:0 0 10px rgba(179,136,255,0.7),0 0 24px rgba(179,136,255,0.3);}
div[data-testid="stExpander"]{background:#0f1520 !important;
  border:1px solid #1a2540 !important;border-radius:4px !important;margin-bottom:3px !important;}
div[data-testid="stExpander"] summary{padding:7px 14px !important;color:#ffffff !important;}
div[data-testid="stExpander"] summary:hover{background:#141e30 !important;}
.ph.mr{border-left-color:#b388ff;color:#b388ff;
  text-shadow:0 0 10px rgba(179,136,255,0.7),0 0 24px rgba(179,136,255,0.3);}
.mr-cell{background:#080d18;border:1px solid #1a2e45;border-radius:6px;padding:12px 14px;}
.mr-scroll-cell{height:340px;overflow-y:auto;box-sizing:border-box;}
.mr-cell-title{font-family:'Orbitron',sans-serif;font-size:0.72rem;color:#b388ff;
  letter-spacing:2px;margin-bottom:8px;border-bottom:1px solid #1a1030;padding-bottom:5px;
  font-weight:700;text-shadow:0 0 10px rgba(179,136,255,0.6),0 0 22px rgba(179,136,255,0.25);}
.verdict-go{background:#061a06;border:2px solid #00e676;border-radius:6px;
  padding:10px 18px;font-family:'Share Tech Mono',monospace;font-size:0.85rem;
  color:#00e676;letter-spacing:2px;margin-bottom:10px;text-align:center;}
.verdict-hold{background:#1a1206;border:2px solid #ffa726;border-radius:6px;
  padding:10px 18px;font-family:'Share Tech Mono',monospace;font-size:0.85rem;
  color:#ffa726;letter-spacing:2px;margin-bottom:10px;text-align:center;}
.verdict-stop{background:#1a0606;border:2px solid #ff4444;border-radius:6px;
  padding:10px 18px;font-family:'Share Tech Mono',monospace;font-size:0.85rem;
  color:#ff4444;letter-spacing:2px;margin-bottom:10px;text-align:center;}
.chk-pass{color:#00e676;font-family:'Share Tech Mono',monospace;font-size:0.72rem;padding:2px 0;}
.chk-fail{color:#ff4444;font-family:'Share Tech Mono',monospace;font-size:0.72rem;padding:2px 0;}
.chk-warn{color:#ffa726;font-family:'Share Tech Mono',monospace;font-size:0.72rem;padding:2px 0;}
.mr-row{display:flex;align-items:center;gap:8px;padding:3px 0;
  border-bottom:1px solid #0a1020;font-family:'Share Tech Mono',monospace;font-size:0.69rem;}
.mr-sym{min-width:90px;color:#00e5ff;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.mr-bar{height:6px;border-radius:3px;}
.mr-val{min-width:60px;text-align:right;color:#c8d8e8;}
.log-scroll-box{height:340px;overflow-y:auto;}
.log-line{font-family:'Share Tech Mono',monospace;font-size:0.68rem;
  line-height:1.55;padding:1px 10px;border-bottom:1px solid #0a1020;
  white-space:pre-wrap;word-break:break-all;}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════
# [SECTION 3] DB FUNCTIONS (통합 읽기)
# ══════════════════════════════════════════════════
def _safe_read_sql(db_path: str, query: str) -> pd.DataFrame:
    """안전하게 SQL 실행, 실패 시 빈 DataFrame 반환"""
    if not os.path.exists(db_path):
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(db_path, timeout=10)
        df = pd.read_sql(query, conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()

def _coerce_numeric_series(series: pd.Series) -> pd.Series:
    def _bytes_to_number(value):
        if isinstance(value, (bytes, bytearray)):
            try:
                return int.from_bytes(value, byteorder="little", signed=False)
            except Exception:
                return 0
        return value
    return pd.to_numeric(series.map(_bytes_to_number), errors='coerce').fillna(0)

def get_live_kr_account_info() -> dict:
    """키움 라이브가 저장한 최신 계좌 총자산 조회 — 1시간 캐시"""
    now_ts = datetime.now().timestamp()
    cached = st.session_state.get('kr_account_cache', None)
    cached_time = st.session_state.get('kr_account_time', 0)
    if cached is not None and (now_ts - cached_time) < 3600:
        return cached
    df = _safe_read_sql(
        DB_KR,
        "SELECT timestamp, total_assets FROM account_info WHERE total_assets > 0 ORDER BY timestamp DESC LIMIT 1",
    )
    if df.empty:
        result = {"timestamp": None, "total_assets": 0.0}
    else:
        try:
            total_assets = float(df["total_assets"].iloc[0] or 0)
        except Exception:
            total_assets = 0.0
        result = {"timestamp": df["timestamp"].iloc[0], "total_assets": total_assets}
    st.session_state['kr_account_cache'] = result
    st.session_state['kr_account_time']  = now_ts
    return result

def load_trade_history() -> Optional[pd.DataFrame]:
    """akros_global.db + akros_kr.db 의 trade_history 통합"""
    dfs = []
    # 해외 매매
    df_global = _safe_read_sql(DB_GLOBAL, "SELECT * FROM trade_history")
    if not df_global.empty:
        dfs.append(df_global)
    # 국내 매매
    df_kr = _safe_read_sql(DB_KR, "SELECT * FROM trade_history")
    if not df_kr.empty:
        dfs.append(df_kr)
    if not dfs:
        return None
    df = pd.concat(dfs, ignore_index=True)
    df.columns = [c.lower() for c in df.columns]
    df["_dt"] = pd.to_datetime(df["time"], errors="coerce")
    # v2.0 신규 GENE 컬럼 (7-GENE 독립팩터 전면 교체)
    numeric_cols = ['entry_price','current_price','pnl_ticks','gene_count',
                    'g02_adx','g09_cmf','atr_val',
                    'pul_main','pul_slope','pul_atr','pul_level0',
                    'kest_trend','g14_score','mst_score',
                    'dsl_osc','sqz_val','sqz_momentum']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = _coerce_numeric_series(df[col])
    return df.sort_values('_dt', ascending=False)

def get_macro_indicators(limit=30) -> pd.DataFrame:
    """argo_macro 테이블에서 최근 limit개 지표"""
    query = f"SELECT * FROM argo_macro ORDER BY collected_at DESC LIMIT {limit}"
    df = _safe_read_sql(DB_MACRO, query)
    if df.empty:
        return df
    # 이름 통일을 위해 market_indicators와 유사하게 매핑 (선택)
    df.rename(columns={'collected_at': 'time', 'symbol': 'indicator_name', 'price': 'value', 'change_pct': 'change'}, inplace=True)
    return df

def get_global_intelligence(limit=12) -> pd.DataFrame:
    """akros_news.db에서 global_intelligence 읽기"""
    query = f"SELECT * FROM global_intelligence ORDER BY time DESC LIMIT {limit}"
    return _safe_read_sql(DB_NEWS, query)

def get_investor_flow(limit=100) -> pd.DataFrame:
    """kr_investor_flow (키움 데이터)"""
    query = f"SELECT * FROM kr_investor_flow ORDER BY date DESC LIMIT {limit}"
    return _safe_read_sql(DB_KR_DATA, query)

# 기존 함수 유지 (호환성)
def get_db_conn():
    try:
        return sqlite3.connect(DB_GLOBAL, check_same_thread=False)
    except Exception:
        return None

def load_db():
    """기존 인터페이스 유지 - 통합 trade_history 반환"""
    return load_trade_history()

def calc_pnl_usd(row, ratio=1.0):
    """
    pnl_ticks에 ratio(부분익절 비율)를 곱한 후 USD 환산.
    STOCK : $1,000 ÷ 진입가 = 수량  → (pnl_ticks * ratio) × qty
    COIN  : $1,000 ÷ 진입가 = 수량  → (pnl_ticks * ratio) × qty
    FUTURE: 3계약 × 종목별 multiplier → (pnl_ticks * ratio) × 3 × mult

    ★ FIX: abs() 제거 — pnl_ticks 부호 그대로 유지.
      DB 저장 기준: pnl_ticks = current_price - entry_price
      LONG 손절: current < entry → pnl_ticks < 0 → 음수 손실 정상 반영
      LONG 익절: current > entry → pnl_ticks > 0 → 양수 이익 정상 반영
      SHORT은 cf=-1로 부호 반전하여 처리 (손절 시 pnl_ticks>0이지만 cf=-1로 음수)
    """
    ep   = float(row.get('entry_price', 0) or 0)
    pt   = float(row.get('pnl_ticks',   0) or 0) * ratio
    at   = str(row.get('assettype', 'STOCK') or 'STOCK').upper()
    sym  = str(row.get('symbol', '')        or '').upper()
    side = str(row.get('side', 'LONG')      or 'LONG').upper()
    cf   = 1 if side == 'LONG' else -1

    if at == 'STOCK':
        qty = max(1, int(POS_STOCK_COIN / ep)) if ep > 0 else 1
        return pt * cf * qty          # ★ abs() 제거
    elif at == 'COIN':
        qty = max(0.001, round(POS_STOCK_COIN / ep, 6)) if ep > 0 else 0.001
        return pt * cf * qty          # ★ abs() 제거
    elif at == 'FUTURE':
        mult = CONTRACT_MULTIPLIERS.get(sym, 1)
        return pt * cf * FUT_CONTRACTS * mult   # ★ abs() 제거
    return pt * cf                              # ★ abs() 제거

def get_exit_ratio(event):
    event = str(event or '').upper()
    return PARTIAL_EXIT_RATIOS.get(event, 1.0)

def estimate_commission(row):
    """포지션 단위 수수료 — 왕복 1회 고정"""
    ep    = float(row.get('entry_price', 0) or 0)
    atype = str(row.get('asset_type', row.get('assettype', 'STOCK')) or 'STOCK').upper()
    if ep <= 0:
        return 0.0
    if atype == 'FUTURE':
        return FUT_CONTRACTS * FUTURE_COMMISSION_PER_CONTRACT_SIDE * 2
    if atype == 'COIN':
        return POS_STOCK_COIN * COIN_COMMISSION_RATE * 2
    shares = max(1, int(POS_STOCK_COIN / ep))
    one_side = max(STOCK_MIN_COMMISSION, shares * STOCK_COMMISSION_PER_SHARE)
    return one_side * 2

def get_ibkr_balance():
    import threading
    now_ts = datetime.now().timestamp()
    cached_bal = st.session_state.get('ibkr_balance', None)
    cached_time = st.session_state.get('ibkr_time', 0)
    if cached_bal is not None and (now_ts - cached_time) < 3600:
        return cached_bal
    try:
        from ibapi.client import EClient
        from ibapi.wrapper import EWrapper
        class IBKRApp(EWrapper, EClient):
            def __init__(self):
                EClient.__init__(self, self)
                self.balance = None
                self.done = threading.Event()
            def accountSummary(self, reqId, account, tag, value, currency):
                if tag == "NetLiquidation" and currency == "USD":
                    self.balance = float(value)
                    self.done.set()
            def accountSummaryEnd(self, reqId):
                self.done.set()
            def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
                if errorCode not in (2104, 2106, 2158, 2119, 2100):
                    self.done.set()
        app = IBKRApp()
        app.connect("127.0.0.1", 4002, clientId=2)
        thread = threading.Thread(target=app.run, daemon=True)
        thread.start()
        time.sleep(1.0)
        app.reqAccountSummary(9001, "All", "NetLiquidation")
        app.done.wait(timeout=5.0)
        app.cancelAccountSummary(9001)
        app.disconnect()
        if app.balance is not None:
            st.session_state['ibkr_balance'] = app.balance
            st.session_state['ibkr_time'] = now_ts
        return app.balance
    except Exception:
        return None


# ══════════════════════════════════════════════════
# [SECTION 4] LIVE SCAN STATUS (변경 없음)
# ══════════════════════════════════════════════════
def get_live_scan_status():
    try:
        if not os.path.exists(LIVE_SCAN_PATH):
            return None
        with open(LIVE_SCAN_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        mtime = os.path.getmtime(LIVE_SCAN_PATH)
        age_sec = time.time() - mtime
        if age_sec > 60:
            data['status'] = 'STALE'
            data['error'] = f'라이브스캔 갱신 중단 {int(age_sec)}초 경과'
        return data
    except Exception as e:
        return {
            "status": "ERROR",
            "current_symbol": "",
            "progress": "",
            "last_update": "--:--",
            "error": str(e)
        }  # 💡 여기에 닫는 괄호가 누락되어 있었던 부분을 보완했습니다.

def get_live_scan_kr_status():
    try:
        if not os.path.exists(LIVE_SCAN_KR_PATH):
            return None
        with open(LIVE_SCAN_KR_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        mtime = os.path.getmtime(LIVE_SCAN_KR_PATH)
        age_sec = time.time() - mtime
        
        # 💡 [핵심 로직 변경] 
        # 파일이 60초 이상 안 바뀌었더라도, 상태가 RUNNING이라면 죽은 게 아니라 '정상 대기 중'으로 판정합니다.
        # 단, 30분(1800초) 이상 아예 무반응이면 그때는 진짜로 엔진이 뻗었거나 꺼진(DEAD) 것으로 판단합니다.
        if 60 < age_sec <= 1800:
            data['status'] = 'WAITING'  # 정상 작동 중인 대기 상태
            data['idle_time'] = int(age_sec)
        elif age_sec > 1800:
            data['status'] = 'DEAD'     # 완전히 멈춘 다운 상태
            data['idle_time'] = int(age_sec)
            
        return data
    except Exception as e:
        return {
            "status": "ERROR",
            "current_symbol": "",
            "last_update": "--:--:--",
            "error": str(e)
        }


# ══════════════════════════════════════════════════
# [SECTION 5] TIME & TRADING STATUS (변경 없음)
# ══════════════════════════════════════════════════
def get_trading_day_window(now=None):
    now = now or datetime.now()
    if now.hour < 6:
        start = datetime.combine(now.date() - timedelta(days=1), datetime.min.time()).replace(hour=6)
    else:
        start = datetime.combine(now.date(), datetime.min.time()).replace(hour=6)
    end = start + timedelta(hours=24)
    return start, end

LOG_GLOBAL = os.path.join(ARGO_DIR, "akros_Global.log")
LOG_KR     = os.path.join(ARGO_DIR, "akros_kr.log")

def read_log_tail(log_path: str, n_lines: int = 80) -> list:
    """로그 파일 끝에서 n_lines 줄 읽기. 파일 없으면 빈 리스트."""
    if not os.path.exists(log_path):
        return []
    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        return [l.rstrip('\n') for l in lines[-n_lines:]]
    except Exception as e:
        return [f"[로그 읽기 오류] {e}"]

def render_log_box(title: str, log_path: str, box_id: str):
    """
    엔진 로그를 스크롤 가능한 박스로 렌더링.
    높이는 보유/종결 박스(340px)와 동일하게 맞춤.
    """
    lines = read_log_tail(log_path, n_lines=80)
    if not lines:
        lines = ["— 로그 없음 (엔진 미실행 또는 경로 확인 필요) —"]

    # 레벨별 색상 매핑
    def _line_color(line: str) -> str:
        ll = line.upper()
        if '[ERROR]'   in ll: return '#ff4444'
        if '[WARNING]' in ll: return '#ffa726'
        if '🚀'        in line or '[ENTRY]' in ll: return '#00e676'
        if '📉'        in line or 'STOP_LOSS' in ll: return '#ff6666'
        if '💸'        in line or 'TP1'      in ll: return '#ffe066'
        if '💵'        in line or 'TP2'      in ll: return '#ffe066'
        if '💰'        in line or 'TP3'      in ll: return '#ffe066'
        if '[INFO]'    in ll: return '#7ecfff'
        return '#4a6a8a'

    rows_html = ''.join(
        f"<div class='log-line' style='color:{_line_color(l)}'>{l}</div>"
        for l in lines
    )
    st.markdown(
        f"<div class='boxtitle'>{title}</div>"
        f"<div class='scroll-box log-scroll-box' id='{box_id}'>"
        f"{rows_html}"
        f"</div>"
        # JS: 최신 로그가 항상 맨 아래로 스크롤
        f"<script>"
        f"(function(){{var b=document.getElementById('{box_id}');"
        f"if(b)b.scrollTop=b.scrollHeight;}})();"
        f"</script>",
        unsafe_allow_html=True
    )


# ══════════════════════════════════════════════════
# [SECTION 6] ANALYTICS ENGINE (기존 함수 대부분 유지, load_db만 수정)
# ══════════════════════════════════════════════════
def _is_kr_stock(symbol):
    try:
        return str(symbol).strip().isdigit() and len(str(symbol).strip()) == 6
    except Exception:
        return False

def detect_violation_entries(df, now=None):
    if df is None or df.empty: return []
    now = now or datetime.now()
    window_start, window_end = get_trading_day_window(now)
    violations = []
    if 'event' not in df.columns: return []
    entries = df[
        (df['event'].str.upper() == 'ENTRY') &
        (df['_dt'] >= window_start) &
        (df['_dt'] < window_end)
    ].copy()
    for _, r in entries.iterrows():
        try:
            dt = r.get('_dt')
            if pd.isna(dt): continue
            h, m = dt.hour, dt.minute
            asset  = str(r.get('assettype', '')).upper()
            symbol = str(r.get('symbol', ''))
            is_kr  = _is_kr_stock(symbol)
            if asset in ('FUTURE', 'COIN') and h < 9:
                violations.append({'sym': symbol, 'time': str(dt)[:16],
                                   'reason': '선물/코인 09:00 이전 진입'})
            if asset == 'STOCK' and not is_kr:
                if h < 22 or (h == 22 and m < 31):
                    violations.append({'sym': symbol, 'time': str(dt)[:16],
                                       'reason': '미국주식 22:31 이전 진입'})
            if asset == 'STOCK' and is_kr:
                if h < 9:
                    violations.append({'sym': symbol, 'time': str(dt)[:16],
                                       'reason': '국내주식 09:00 이전 진입'})
        except Exception:
            continue
    return violations

def analyze_trades(df):
    """
    포지션(진입) 단위로 집계.
    TP1→TP2→TP3처럼 부분청산이 여러 번 발생해도 1개 포지션으로 카운트.
    포지션 총 PnL = 각 이벤트 PnL 합산.
    최종 청산 이벤트(STOP_LOSS 등)가 있는 포지션만 완결 트레이드로 집계.
    """
    empty = dict(
        wr=None, pl=None, mdd=0, sharpe=0, sortino=0,
        total=0, wins=0, losses=0, expectancy=0,
        trade_details=[], monthly_count=0
    )
    if df is None or df.empty: return empty

    ev_col = 'event' if 'event' in df.columns else None
    if not ev_col: return empty

    CLOSE_SET = set(e.upper() for e in CLOSE_EVTS)
    FINAL_SET = set(e.upper() for e in FINAL_EXIT_EVTS)

    df_sorted = df.sort_values('_dt', ascending=True)

    # ── 포지션 단위 재생 ──────────────────────────────
    open_pos = {}   # sym → 진행 중 포지션 dict
    completed = []  # 완결된 포지션 list

    for _, r in df_sorted.iterrows():
        sym   = str(r.get('symbol', '') or '').strip()
        ev    = str(r.get('event',  '') or '').strip().upper()
        dt    = r.get('_dt', pd.NaT)
        if not sym or not ev:
            continue

        # 진입
        if ev in ENTRY_EVTS:
            open_pos[sym] = {
                'sym'        : sym,
                'asset_type' : str(r.get('assettype', 'STOCK') or 'STOCK').upper(),
                'side'       : str(r.get('side', 'LONG') or 'LONG').upper(),
                'entry_price': float(r.get('entry_price', 0) or 0),
                'grade'      : str(r.get('grade', 'C') or 'C').upper(),
                'total_pnl'  : 0.0,
                'last_event' : ev,
                'exit_time'  : dt,
                'remaining'  : 1.0,   # ★ FIX: remaining 추적 추가
            }
            continue

        # 청산 이벤트
        if ev in CLOSE_SET and sym in open_pos:
            pos       = open_pos[sym]
            remaining = pos.get('remaining', 1.0)
            # ★ FIX: PARTIAL은 정해진 비율, FINAL은 남은 수량(remaining) 전량으로 계산
            if ev in PARTIAL_EXIT_RATIOS:
                ratio = min(PARTIAL_EXIT_RATIOS[ev], remaining)
            else:
                ratio = remaining  # STOP_LOSS/EOD_FORCE_CLOSE 등 → 잔여 수량만
            pnl_usd = calc_pnl_usd(r, ratio)
            pos['total_pnl'] += pnl_usd
            pos['last_event'] = ev
            pos['exit_time']  = dt
            # remaining 차감
            pos['remaining'] = max(0.0, remaining - ratio)

            # 최종 청산이면 완결 처리
            if ev in FINAL_SET:
                completed.append(dict(pos))
                del open_pos[sym]
            # 부분청산(TP1/TP2 등)은 open_pos 유지 → 계속 누적

    # trade_details 생성 (포지션 단위)
    trade_details = []
    for pos in completed:
        total_pnl = pos['total_pnl']
        trade_details.append({
            'sym'        : pos['sym'],
            'asset_type' : pos['asset_type'],   # ★ FIX: 'STOCK' 하드코딩 → 실제 자산군
            'side'       : pos['side'],
            'entry_price': pos['entry_price'],
            'pnl_ticks'  : 0.0,
            'pnl_pct'    : total_pnl,
            'total_pnl'  : total_pnl,
            'is_win'     : total_pnl > 0,
            'event'      : pos['last_event'],
            'exit_time'  : pos['exit_time'],
            'grade'      : pos['grade'],
        })

    # ── 미완결 포지션(TP1/TP2 부분익절 후 오픈): 확정된 부분익절 PnL 합산
    # ★ FIX: 미완결 포지션은 승률/손익비 통계에서 제외 (open_partial_pnl로만 누계)
    #   TP1 도달 후 오픈 종목을 is_win=True로 집계하면 승률 인위 상승 + 손익비 왜곡
    open_partial_pnl = sum(
        pos['total_pnl'] for pos in open_pos.values()
        if pos['total_pnl'] != 0.0
    )

    if not trade_details:
        return empty

    wins   = sum(1 for t in trade_details if t['is_win'])
    losses = len(trade_details) - wins
    total  = len(trade_details)
    wr     = wins / total * 100 if total > 0 else None
    win_p  = [t['total_pnl'] for t in trade_details if t['is_win']]
    loss_p = [abs(t['total_pnl']) for t in trade_details if not t['is_win']]
    avg_w  = float(np.mean(win_p))  if win_p  else 0.0
    avg_l  = float(np.mean(loss_p)) if loss_p else 0.0
    pl     = avg_w / avg_l if avg_l > 0 else (float('inf') if avg_w > 0 else None)
    exp    = (wr/100 * avg_w - (1 - wr/100) * avg_l) if wr is not None else 0

    now = datetime.now()
    monthly = 0
    if df is not None and not df.empty and 'event' in df.columns:
        monthly = int(df[
            (df['event'].str.upper().isin({'ENTRY', 'GITMO_ENTRY'})) &
            (df['_dt'].dt.year  == now.year) &
            (df['_dt'].dt.month == now.month)
        ].shape[0])

    pnl_series = [t['total_pnl'] for t in trade_details]
    if pnl_series:
        initial_capital = float(SEED_CAPITAL)
        cum_pnl = np.cumsum(pnl_series)
        equity = np.array([initial_capital] + list(initial_capital + cum_pnl))
        peak = np.maximum.accumulate(equity)
        peak_safe = np.where(peak == 0, 1.0, peak) 
        dd = (equity - peak_safe) / peak_safe * 100
        actual_mdd = float(dd.min())
    else:
        actual_mdd = 0.0
        
    if len(pnl_series) > 1:
        ret_arr  = np.array(pnl_series, dtype=float) / SEED_CAPITAL
        avg_r    = float(np.mean(ret_arr))
        std_r    = float(np.std(ret_arr, ddof=1))
        downside = np.minimum(ret_arr, 0.0)
        down_dev = float(np.sqrt(np.mean(np.square(downside))))
        annual_factor = np.sqrt(len(ret_arr))
        sharpe  = round((avg_r / std_r) * annual_factor, 2) if std_r > 0 else 0.0
        # 손실 트레이드 최소 3건 이상일 때만 소르티노 의미 있음
        loss_cnt = sum(1 for r in ret_arr if r < 0)
        sortino = round((avg_r / down_dev) * annual_factor, 2) if (down_dev > 0 and loss_cnt >= 3) else 0.0
    else:
        sharpe, sortino = 0.0, 0.0

    # ★ equity_curve: 시각화용 자산 곡선 데이터 반환 (exit_time 기반 시계열)
    equity_curve = []
    if pnl_series:
        _cum = float(SEED_CAPITAL)
        for t in trade_details:
            _cum += t['total_pnl']
            _et = t.get('exit_time')
            if _et is not None and pd.notna(_et):
                try:
                    equity_curve.append({'time': pd.Timestamp(_et), 'equity': round(_cum, 2)})
                except Exception:
                    pass

    return dict(wr=wr, pl=pl, mdd=actual_mdd, sharpe=sharpe, sortino=sortino,
                total=total, wins=wins, losses=losses, expectancy=exp,
                trade_details=trade_details, monthly_count=monthly,
                open_partial_pnl=open_partial_pnl,
                equity_curve=equity_curve)  # ★ 자산곡선 시계열 추가

def calc_stats_by_type(trade_details, asset_type):
    filtered = [t for t in trade_details if t.get('asset_type') == asset_type]
    if not filtered: return dict(wr=None, pl=None, total=0, wins=0, losses=0)
    wins   = sum(1 for t in filtered if t['is_win'])
    losses = len(filtered) - wins
    closed = wins + losses
    wr     = wins / closed * 100 if closed > 0 else None
    win_p  = [t['pnl_pct'] for t in filtered if t['is_win']]
    loss_p = [abs(t['pnl_pct']) for t in filtered if not t['is_win']]
    avg_w  = np.mean(win_p)  if win_p  else None
    avg_l  = np.mean(loss_p) if loss_p else None
    pl     = avg_w / avg_l if (avg_w and avg_l and avg_l > 0) else None
    return dict(wr=wr, pl=pl, total=closed, wins=wins, losses=losses)

def filter_trade_details_by_window(trade_details, start_dt, end_dt):
    return [t for t in trade_details
            if pd.notna(t.get('exit_time')) and start_dt <= t['exit_time'] < end_dt]

def get_open_closed(df, start_dt=None, end_dt=None):
    if df is None or df.empty:
        return [], []
    ev_col = 'event' if 'event' in df.columns else None
    if not ev_col:
        return [], []

    CLOSE_SET = set(e.upper() for e in CLOSE_EVTS)
    PARTIAL_SET = set(PARTIAL_EXIT_RATIOS)
    FINAL_SET = set(e.upper() for e in FINAL_EXIT_EVTS)
    df_sorted = df.sort_values('_dt', ascending=True)

    open_map    = {}
    closed_list = []

    for _, r in df_sorted.iterrows():
        sym = str(r.get('symbol', '') or '').strip()
        ev  = str(r.get('event',  '') or '').strip().upper()
        dt  = r.get('_dt', pd.NaT)
        if not sym or not ev:
            continue

        if ev in ENTRY_EVTS:
            open_map[sym] = {
                'sym'       : sym,
                'price'     : float(r.get('entry_price', 0) or 0),
                'grade'     : str(r.get('grade', 'C') or 'C').strip().upper() or 'C',
                'gcnt'      : int(float(r.get('gene_count', 0) or 0)),
                'side'      : str(r.get('side', 'LONG') or 'LONG').strip().upper() or 'LONG',
                'time'      : str(r.get('time', '')),
                'entry_dt'  : dt,
                'asset_type': str(r.get('assettype', 'STOCK') or 'STOCK').strip().upper() or 'STOCK',
                'event'     : ev,
                'remaining' : 1.0,
                'last_event': ev,
                # 신규 7-GENE 표시용
                'kest_trend'  : int(float(r.get('kest_trend', 0) or 0)),
                'mst_score'   : float(r.get('mst_score', 50) or 50),
                'sqz_momentum': int(float(r.get('sqz_momentum', 0) or 0)),
            }
            continue

        if ev in CLOSE_SET:
            pnl_ticks_raw = float(r.get('pnl_ticks', 0) or 0)
            atype_r   = str(r.get('assettype', 'STOCK') or 'STOCK').strip().upper() or 'STOCK'
            em        = open_map.get(sym, {})
            ep        = em.get('price', float(r.get('entry_price', 0) or 0))
            # ★ FIX: FINAL 이벤트는 remaining 기준으로 계산
            cur_remaining = em.get('remaining', 1.0)
            if ev in PARTIAL_EXIT_RATIOS:
                ratio = min(PARTIAL_EXIT_RATIOS[ev], cur_remaining)
            else:
                ratio = cur_remaining  # STOP_LOSS 등: 남은 수량만
            scaled_pnl_ticks = pnl_ticks_raw * ratio
            _row_dict = {
                'entry_price': ep,
                'pnl_ticks'  : scaled_pnl_ticks,
                'assettype'  : atype_r,
                'symbol'     : sym,
                'side'       : em.get('side', str(r.get('side', 'LONG') or 'LONG').upper()),
            }
            pnl_usd = calc_pnl_usd(_row_dict, 1.0)  # 이미 비율 적용

            in_window = True
            if start_dt is not None and end_dt is not None:
                in_window = pd.notna(dt) and (start_dt <= dt < end_dt)

            if in_window:
                closed_list.append({
                    'sym'        : sym,
                    'entry_price': ep,
                    'close_price': float(r.get('current_price', 0) or 0),
                    'grade'      : em.get('grade', str(r.get('grade', 'C') or 'C').strip().upper()) or 'C',
                    'side'       : em.get('side',  str(r.get('side', 'LONG') or 'LONG').strip().upper()) or 'LONG',
                    'event'      : ev,
                    'time'       : str(r.get('time', '')),
                    'asset_type' : em.get('asset_type', atype_r),
                    'total_pnl'  : pnl_usd,
                    'pnl_ticks'  : scaled_pnl_ticks,
                    'is_win'     : pnl_usd > 0,
                })

            if ev in PARTIAL_SET and sym in open_map:
                open_map[sym]['remaining'] = max(0.0, cur_remaining - PARTIAL_EXIT_RATIOS[ev])
                open_map[sym]['last_event'] = ev
                continue

            if ev in FINAL_SET:
                open_map.pop(sym, None)

    open_list = list(open_map.values())
    if start_dt is not None:
        open_list = [t for t in open_list if pd.notna(t.get('entry_dt')) and t['entry_dt'] >= start_dt]
    return (
        sorted(open_list,   key=lambda x: x['time'], reverse=True),
        sorted(closed_list, key=lambda x: x['time'], reverse=True),
    )

def get_closed_records(df, start_dt=None, end_dt=None):
    _, closed = get_open_closed(df, start_dt, end_dt)
    return closed


# ══════════════════════════════════════════════════
# [SECTION 7] ASSET BAR (IBKR 연동) - 변경 없음
# ══════════════════════════════════════════════════
def calc_asset_status(db_global, trade_details_all, open_list, s_all, now):
    """해외 파트: 이벤트 발생 시점 기준 Realized PnL 추적 로직"""
    window_start, window_end = get_trading_day_window(now)

    # 1. 누적 손익 (완결 포지션 기준 유지)
    cumulative_pnl = sum(float(t.get('total_pnl', 0) or 0) for t in trade_details_all)
    cumulative_commission = sum(estimate_commission(t) for t in trade_details_all)

    # 2. 당일/당월 실현 손익 (이벤트 기반 정밀 추적)
    daily_gross_pnl  = 0.0
    daily_commission = 0.0
    monthly_pnl      = 0.0
    monthly_commission = 0.0

    if db_global is not None and not db_global.empty:
        CLOSE_SET = set(e.upper() for e in CLOSE_EVTS)
        FINAL_SET = set(e.upper() for e in FINAL_EXIT_EVTS)

        db_sorted = db_global.sort_values('_dt', ascending=True)
        open_pos  = {}   # sym → {remaining, entry_price, assettype}

        for _, r in db_sorted.iterrows():
            sym = str(r.get('symbol', '') or '').strip()
            ev  = str(r.get('event',  '') or '').upper()
            dt  = r.get('_dt', pd.NaT)
            if not sym or not ev:
                continue

            if ev in ENTRY_EVTS:
                open_pos[sym] = {
                    'remaining' : 1.0,
                    'entry_price': float(r.get('entry_price', 0) or 0),
                    'assettype' : str(r.get('assettype', 'STOCK') or 'STOCK').upper(),
                    'side'      : str(r.get('side', 'LONG') or 'LONG').upper(),
                    'symbol'    : sym,
                }
                continue

            if ev in CLOSE_SET and sym in open_pos:
                pos = open_pos[sym]
                rem = pos['remaining']
                ratio = min(PARTIAL_EXIT_RATIOS.get(ev, 1.0), rem) if ev in PARTIAL_EXIT_RATIOS else rem

                # row를 dict로 변환하여 calc_pnl_usd에 안전하게 전달
                row_dict = {
                    'entry_price': pos['entry_price'],
                    'pnl_ticks'  : float(r.get('pnl_ticks', 0) or 0),
                    'assettype'  : pos['assettype'],
                    'symbol'     : sym,
                    'side'       : pos['side'],
                }
                pnl_usd = calc_pnl_usd(row_dict, ratio)

                # 수수료: 포지션 1회 왕복 기준 × ratio (비율만큼만 청산)
                ep = pos['entry_price']
                at = pos['assettype']
                if at == 'FUTURE':
                    comm_base = FUT_CONTRACTS * FUTURE_COMMISSION_PER_CONTRACT_SIDE * 2
                elif at == 'COIN':
                    comm_base = POS_STOCK_COIN * COIN_COMMISSION_RATE * 2
                else:
                    shares   = max(1, int(POS_STOCK_COIN / ep)) if ep > 0 else 1
                    one_side = max(STOCK_MIN_COMMISSION, shares * STOCK_COMMISSION_PER_SHARE)
                    comm_base = one_side * 2
                comm_usd = comm_base * ratio

                if pd.notna(dt):
                    if window_start <= dt < window_end:
                        daily_gross_pnl  += pnl_usd
                        daily_commission += comm_usd
                    if dt.year == now.year and dt.month == now.month:
                        monthly_pnl        += pnl_usd
                        monthly_commission += comm_usd

                pos['remaining'] = max(0.0, rem - ratio)
                if ev in FINAL_SET:
                    del open_pos[sym]

    daily_pnl = daily_gross_pnl - daily_commission

    # 3. 기타 지표 계산
    mfe_values = []
    trade_details_today = [t for t in trade_details_all if pd.notna(t.get('exit_time')) and window_start <= pd.to_datetime(t['exit_time']) < window_end]
    for t in trade_details_today:
        ep = float(t.get('entry_price', 0) or 0)
        pt = float(t.get('pnl_ticks', 0) or 0)
        if ep > 0:
            mfe_values.append(pt / ep * 100)
    mfe_pct = max([v for v in mfe_values if v > 0], default=0.0)

    open_pnl       = float(s_all.get('open_partial_pnl', 0.0))
    ibkr_bal       = get_ibkr_balance()
    ibkr_connected = ibkr_bal is not None

    total_assets = ibkr_bal if ibkr_connected else SEED_CAPITAL + (cumulative_pnl - cumulative_commission) + open_pnl

    mdd_val    = s_all.get('mdd', 0.0) or 0.0
    mdd_abs    = abs(mdd_val)
    mdd_dollar = SEED_CAPITAL * (mdd_abs / 100)
    net_pnl    = cumulative_pnl - cumulative_commission
    recovery_factor = round(net_pnl / mdd_dollar, 2) if mdd_dollar > 0 else 0.0

    return dict(
        total=total_assets, cum_pnl=net_pnl, daily_pnl=daily_pnl,
        monthly_pnl=monthly_pnl, monthly_commission=monthly_commission,
        open_pnl=open_pnl, open_cnt=len(open_list),
        monthly_cnt=s_all.get('monthly_count', 0), ibkr_connected=ibkr_connected,
        expectancy=s_all.get('expectancy', 0), mfe_pct=mfe_pct,
        recovery_factor=recovery_factor, mdd_pct=mdd_abs,
    )

def render_asset_bar(a, s_all=None):
    ibkr_tag  = "🔗 IBKR" if a.get('ibkr_connected') else "📁 DB"
    pnl_cls   = 'av-profit' if a['daily_pnl'] >= 0 else 'av-loss'
    cum_cls   = 'av-profit' if a['cum_pnl']   >= 0 else 'av-loss'
    open_pnl  = a.get('open_pnl', 0.0) or 0.0
    open_cls  = 'av-profit' if open_pnl >= 0 else 'av-loss'
    exp_val   = a.get('expectancy', 0) or 0
    exp_str   = f"{exp_val:+.2f}" if exp_val != 0 else "—"
    exp_cls   = 'av-profit' if exp_val >= 0 else 'av-loss'
    # SQN — (평균손익 ÷ 손익표준편차) × √매매횟수
    _sqn_trades = (s_all or {}).get('trade_details', [])
    _sqn_pnls   = [t.get('total_pnl', 0) for t in _sqn_trades]
    if len(_sqn_pnls) >= 2:
        import numpy as _np
        _sqn_mean = float(_np.mean(_sqn_pnls))
        _sqn_std  = float(_np.std(_sqn_pnls, ddof=1))
        _sqn_val  = (_sqn_mean / _sqn_std) * (_np.sqrt(len(_sqn_pnls))) if _sqn_std > 0 else 0.0
    else:
        _sqn_val = 0.0
    sqn_str = f"{_sqn_val:.2f}" if _sqn_val != 0.0 else "—"
    sqn_cls = 'av-profit' if _sqn_val >= 2.0 else ('av-neutral' if _sqn_val >= 1.0 else 'av-loss')
    rf        = a.get('recovery_factor', 0.0) or 0.0
    mdd_pct   = a.get('mdd_pct', 0.0) or 0.0
    rf_cls    = 'av-profit' if rf >= 2.0 else ('av-neutral' if rf >= 1.0 else 'av-loss')
    rf_str    = f"{rf:.2f}" if rf != 0.0 else "—"
    # Profit Factor — trade_details 기반 실계산
    _trades   = (s_all or {}).get('trade_details', [])
    _pf_w     = sum(t['total_pnl'] for t in _trades if t.get('total_pnl', 0) > 0)
    _pf_l     = abs(sum(t['total_pnl'] for t in _trades if t.get('total_pnl', 0) < 0))
    _pf_val   = _pf_w / _pf_l if _pf_l > 0 else float('inf') if _pf_w > 0 else 0.0
    pf_str    = "—" if _pf_val == 0.0 else ("∞" if _pf_val == float('inf') else f"{_pf_val:.2f}")
    pf_cls    = 'av-profit' if _pf_val >= 2.0 else ('av-neutral' if _pf_val >= 1.0 else 'av-loss')
    st.markdown(f"""
    <div class="asset-bar">
      <div class="asset-cell">
        <span class="asset-lbl">{ibkr_tag} 총 운용 자산</span>
        <span class="asset-val av-total">${a['total']:,.2f}</span>
        <span class="asset-sub {cum_cls}">누적 손익: {a['cum_pnl']:+,.2f}</span>
      </div>
      <div class="asset-cell">
        <span class="asset-lbl">📊 당일 순손익</span>
        <span class="asset-val {pnl_cls}">${a['daily_pnl']:+,.2f}</span>
        <span class="asset-sub {open_cls}">Open PnL: ${open_pnl:+,.2f}</span>
      </div>
      <div class="asset-cell">
        <span class="asset-lbl">🎯 기대값 (EXPECTANCY)</span>
        <span class="asset-val {exp_cls}">${exp_str}</span>
        <span class="asset-sub">트레이딩당 평균 기대수익</span>
      </div>
      <div class="asset-cell">
        <span class="asset-lbl">📊 SQN (SYSTEM QUALITY NUMBER)</span>
        <span class="asset-val {sqn_cls}">{sqn_str}</span>
        <span class="asset-sub">2.0+ 우수 / 1.0+ 양호</span>
      </div>
      <div class="asset-cell">
        <span class="asset-lbl">📐 회복계수 (RECOVERY FACTOR)</span>
        <span class="asset-val {rf_cls}">{rf_str}</span>
        <span class="asset-sub">순이익 ÷ MDD (-{mdd_pct:.2f}%)</span>
      </div>
      <div class="asset-cell">
        <span class="asset-lbl">💹 수익원지수 (PROFIT FACTOR)</span>
        <span class="asset-val {pf_cls}">{pf_str}</span>
        <span class="asset-sub">총익절합 ÷ 총손절합</span>
      </div>
    </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════
# [SECTION 8] RENDER FUNCTIONS (기존과 동일, 생략)
# ══════════════════════════════════════════════════
def render_live_scan_banner(scan_status, is_kr=False):
    """
    해외 및 국내 라이브 스캔 배너를 통합하여 그려주는 함수
    """
    if scan_status:
        status = scan_status.get('status', 'UNKNOWN')
        err = scan_status.get('error', '')
        sym = scan_status.get('current_symbol', '---')
        upd = scan_status.get('last_update', '--:--')
        
        # 1️⃣ [RUNNING] 실시간 스캔 중
        if status == "RUNNING":
            if is_kr:
                grade = scan_status.get('grade', '-')
                gene  = scan_status.get('gene_count', 0)
                strat = scan_status.get('strategy', 'INTRA')
                st.markdown(
                    f"<div class='scan-banner running'>"
                    f"📡 KR &nbsp;|&nbsp; <span class='scan-symbol'>{sym}</span> "
                    f"[<span class='scan-progress'>{strat}</span>] "
                    f"&nbsp;·&nbsp; <span style='color:#ffe066;font-weight:700'>{grade}</span>"
                    f" <span style='color:#b388ff'>G{gene}/7</span> "
                    f"&nbsp;|&nbsp; 최근 활동: {upd}</div>",
                    unsafe_allow_html=True
                )
            else:
                prog = scan_status.get('progress', '0/0')
                st.markdown(
                    f"<div class='scan-banner running'>"
                    f"📡 US &nbsp;|&nbsp; <span class='scan-symbol'>{sym}</span> "
                    f"[<span class='scan-progress'>{prog}</span>] "
                    f"&nbsp;|&nbsp; 최근 활동: {upd}</div>",
                    unsafe_allow_html=True
                )

        # 2️⃣ [WAITING] 정상 대기 중
        elif status == "WAITING":
            idle_sec = scan_status.get('idle_time', 0)
            idle_str = f"{idle_sec // 60}분 전" if idle_sec >= 60 else f"{idle_sec}초 전"
            prefix_tag = "KR" if is_kr else "US"
            st.markdown(
                f"<div class='scan-banner idle'>"
                f"⏸ {prefix_tag} &nbsp;|&nbsp; SIGNAL STANDBY "
                f"&nbsp;·&nbsp; 조건검색 대기 중 "
                f"&nbsp;|&nbsp; 최근: {upd} &nbsp;({idle_str} 경과)</div>",
                unsafe_allow_html=True
            )

        # 3️⃣ [DEAD / ERROR / STALE] 통신 끊김
        elif status in ["DEAD", "ERROR", "STALE"]:
            idle_sec = scan_status.get('idle_time', 0)
            prefix_tag = "KR" if is_kr else "US"
            st.markdown(
                f"<div class='scan-banner idle' style='border-color:#ff4444;color:#ff4444;'>"
                f"🚨 {prefix_tag} &nbsp;|&nbsp; ENGINE OFFLINE "
                f"&nbsp;·&nbsp; 마지막 수신 {int(idle_sec // 60)}분 경과 "
                f"&nbsp;|&nbsp; 엔진 가동 상태 확인 필요</div>",
                unsafe_allow_html=True
            )
    else:
        prefix_tag = "KR" if is_kr else "US"
        label = "Akros_KR.py 미실행" if is_kr else "Akros_Global.py 미실행"
        st.markdown(
            f"<div class='scan-banner idle'>"
            f"🔍 {prefix_tag} &nbsp;|&nbsp; ENGINE STANDBY "
            f"&nbsp;·&nbsp; {label}</div>",
            unsafe_allow_html=True
        )

def kpi_card(label, val, cls, sub=""):
    s = f"<div class='kpi-sub'>{sub}</div>" if sub else ""
    return (f"<div class='kpi {cls}'><div class='kpi-lbl'>{label}</div>"
            f"<div class='kpi-val {cls}'>{val}</div>{s}</div>")

def fmt_ratio_value(value, suffix=":1", prefix=""):
    if value is None: return "—"
    if value == float('inf'): return "∞"
    return f"{prefix}{value:.2f}{suffix}"

def render_part1(s, trades):
    wr  = f"{s['wr']:.1f}%" if s['wr'] is not None else "—"
    pl  = fmt_ratio_value(s['pl'])
    mdd_val = s.get('mdd', 0.0) or 0.0
    mdd = f"{mdd_val:.2f}%"
    sub = f"{s['wins']}W / {s['losses']}L / 총 {s['total']}트레이드"
    pl_num = s.get('pl') or 0
    wr_num = (s.get('wr') or 0) / 100
    rr_val = pl_num * wr_num / (1 - wr_num) if (wr_num > 0 and wr_num < 1 and pl_num > 0) else 0
    rr_str = f"{rr_val:.2f}:1" if rr_val > 0 else "—"
    cols = st.columns(6)
    cards = [
        kpi_card("승률",         wr,                   "c2", sub),
        kpi_card("손익비",       pl,                   "c4", "평균 손익비"),
        kpi_card("MDD",         mdd,                   "c3", "누적대비"),
        kpi_card("샤프비율",    f"{s['sharpe']:.2f}",  "c6", "위험조정수익률"),
        kpi_card("소르티노",    f"{s['sortino']:.2f}", "c5", "하방리스크 조정"),
        kpi_card("리스크보상",   rr_str,               "c1", "리스크대비보상"),
    ]
    for i, c in enumerate(cols):
        c.markdown(cards[i], unsafe_allow_html=True)

def render_part2(trades):
    fut  = calc_stats_by_type(trades, 'FUTURE')
    coin = calc_stats_by_type(trades, 'COIN')
    stk  = calc_stats_by_type(trades, 'STOCK')
    def wr(s): return f"{s['wr']:.1f}%" if s['wr'] is not None else "—"
    def pl(s): return fmt_ratio_value(s['pl'])
    def sub(s): return f"{s['wins']}W/{s['losses']}L/{s['total']}건"
    cols = st.columns(6)
    cards = [
        kpi_card("선물 승률",   wr(fut),  "c1", sub(fut)),
        kpi_card("선물 손익비", pl(fut),  "c4", "선물"),
        kpi_card("코인 승률",   wr(coin), "c6", sub(coin)),
        kpi_card("코인 손익비", pl(coin), "c4", "코인"),
        kpi_card("주식 승률",   wr(stk),  "c2", sub(stk)),
        kpi_card("주식 손익비", pl(stk),  "c4", "주식"),
    ]
    for i, c in enumerate(cols):
        c.markdown(cards[i], unsafe_allow_html=True)

# ══════════════════════════════════════════════════
# [SECTION 2-KR] 국내주식 전용 파트 (akros_kr.db)
# ══════════════════════════════════════════════════
KR_SEED_CAPITAL    =  2_000_000   # 종목당 시드 (KR) — 사이징 기준 유지
KR_DISPLAY_CAPITAL = 80_000_000   # 대시보드 총운용자산 표기 기준 (고정)
KR_COMMISSION_RATE = 0.002    # 키움 수수료율 (편도)
KR_COMMISSION_FIXED = 4_600       # 종목당 왕복 수수료+세금 고정값 (매수2300+매도2300)

def load_kr_trade_history() -> Optional[pd.DataFrame]:
    """akros_kr.db 전용 trade_history 로드"""
    df = _safe_read_sql(DB_KR, "SELECT * FROM trade_history")
    if df.empty:
        return None
    df.columns = [c.lower() for c in df.columns]
    df["_dt"] = pd.to_datetime(df["time"], errors="coerce")
    for col in ['entry_price','current_price','pnl_ticks','gene_count']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    return df.sort_values('_dt', ascending=False)

def calc_kr_pnl_krw(row, ratio=1.0):
    """국내주식 PnL 계산 (KRW): pnl_ticks = 현재가 - 진입가"""
    ep  = float(row.get('entry_price', 0) or 0)
    pt  = float(row.get('pnl_ticks',   0) or 0) * ratio
    qty = max(1, int(KR_SEED_CAPITAL / ep)) if ep > 0 else 1
    return pt * qty

def _kr_close_ratio(event, remaining):
    """
    부분청산 후 최종청산은 남은 수량만 반영.
    ★ FIX 확인: PARTIAL_EXIT_RATIOS에 없는 이벤트(STOP_LOSS, TP3_TREND_END 등)는
      remaining 전량 기준으로 계산 — 이미 올바른 로직.
      TP3_TREND_END → remaining(예: 0.2) 기준 전량 청산 정상 반영.
    """
    remaining = max(0.0, min(float(remaining or 0.0), 1.0))
    if event in PARTIAL_EXIT_RATIOS:
        return min(PARTIAL_EXIT_RATIOS[event], remaining)
    return remaining  # FINAL 이벤트: 남은 수량 전량

def estimate_kr_commission(row):
    """
    종목당 2,000,000원 고정 진입 기준.
    수수료+세금 = 왕복 4,600원 고정.
    청산 이벤트 1건당 4,600원만 계상 (ENTRY는 제외 — 이중계산 방지).
    부분익절(TP1/TP2)은 해당 비율만큼 배분.
    """
    event = str(row.get('event', '') or '').upper()
    if event in ENTRY_EVTS:
        return 0.0   # ENTRY는 수수료 계상 안 함 — 청산 시 왕복 전액 반영
    ratio = PARTIAL_EXIT_RATIOS.get(event, 1.0)
    return KR_COMMISSION_FIXED * ratio

def analyze_kr_trades(df):
    """국내주식 전용 분석 엔진 — 포지션 단위 집계"""
    empty = dict(wr=None, pl=None, mdd=0, sharpe=0, sortino=0,
                 total=0, wins=0, losses=0, expectancy=0,
                 trade_details=[], monthly_count=0)
    if df is None or df.empty: return empty
    ev_col = 'event' if 'event' in df.columns else None
    if not ev_col: return empty

    CLOSE_SET = set(e.upper() for e in CLOSE_EVTS)
    FINAL_SET = set(e.upper() for e in FINAL_EXIT_EVTS)

    df_sorted = df.sort_values('_dt', ascending=True)
    open_pos  = {}
    completed = []

    for _, r in df_sorted.iterrows():
        sym = str(r.get('symbol', '') or '').strip()
        ev  = str(r.get('event',  '') or '').strip().upper()
        dt  = r.get('_dt', pd.NaT)
        if not sym or not ev:
            continue

        if ev in ENTRY_EVTS:
            open_pos[sym] = {
                'sym'        : sym,
                'asset_type' : 'STOCK',
                'side'       : str(r.get('side', 'LONG') or 'LONG').upper(),
                'entry_price': float(r.get('entry_price', 0) or 0),
                'grade'      : str(r.get('grade', 'C') or 'C').upper(),
                'total_pnl'  : 0.0,
                'last_event' : ev,
                'exit_time'  : dt,
                'remaining'  : 1.0,
            }
            continue
        
        if ev in CLOSE_SET and sym in open_pos:
            pos     = open_pos[sym]
            ep      = pos['entry_price']
            pt      = float(r.get('pnl_ticks', 0))
            qty     = max(1, int(KR_SEED_CAPITAL / ep)) if ep > 0 else 1
            remaining = pos.get('remaining', 1.0)
            close_ratio = _kr_close_ratio(ev, remaining)
            pnl = pt * qty * close_ratio
            pos['total_pnl'] += pnl
            pos['last_event'] = ev
            pos['exit_time']  = dt
            pos['remaining'] = max(0.0, float(remaining or 0.0) - close_ratio)

            if ev in FINAL_SET:
                completed.append(dict(pos))
                del open_pos[sym]

    trade_details = []
    for pos in completed:
        total_pnl = pos['total_pnl']
        trade_details.append({
            'sym'        : pos['sym'],
            'asset_type' : 'STOCK',
            'side'       : pos['side'],
            'entry_price': pos['entry_price'],
            'pnl_ticks'  : 0.0,
            'pnl_pct'    : total_pnl,
            'total_pnl'  : total_pnl,
            'is_win'     : total_pnl > 0,
            'event'      : pos['last_event'],
            'exit_time'  : pos['exit_time'],
            'grade'      : pos['grade'],
        })

    if not trade_details:
        return empty

    wins   = sum(1 for t in trade_details if t['is_win'])
    losses = len(trade_details) - wins
    total  = len(trade_details)
    wr     = wins / total * 100 if total > 0 else None
    win_p  = [t['total_pnl'] for t in trade_details if t['is_win']]
    loss_p = [abs(t['total_pnl']) for t in trade_details if not t['is_win']]
    avg_w  = float(np.mean(win_p))  if win_p  else 0.0
    avg_l  = float(np.mean(loss_p)) if loss_p else 0.0
    pl     = avg_w / avg_l if avg_l > 0 else None
    exp    = (wr/100 * avg_w - (1 - wr/100) * avg_l) if wr is not None else 0

    now = datetime.now()
    monthly = 0
    if df is not None and not df.empty and 'event' in df.columns:
        monthly = int(df[
            (df['event'].str.upper().isin({'ENTRY', 'GITMO_ENTRY'})) &
            (df['_dt'].dt.year  == now.year) &
            (df['_dt'].dt.month == now.month)
        ].shape[0])

    pnl_series = [t['total_pnl'] for t in trade_details]
    if pnl_series:
        equity = np.array([KR_DISPLAY_CAPITAL] + list(np.cumsum(pnl_series) + KR_DISPLAY_CAPITAL))
        peak   = np.maximum.accumulate(equity)
        dd     = (equity - peak) / peak * 100
        actual_mdd = float(dd.min())
    else:
        actual_mdd = 0.0

    if len(pnl_series) > 1:
        ret_arr  = np.array(pnl_series, dtype=float) / KR_DISPLAY_CAPITAL
        avg_r    = float(np.mean(ret_arr))
        std_r    = float(np.std(ret_arr, ddof=1))
        downside = np.minimum(ret_arr, 0.0)
        down_dev = float(np.sqrt(np.mean(np.square(downside))))
        annual_factor = np.sqrt(len(ret_arr))
        sharpe  = round((avg_r / std_r) * annual_factor, 2) if std_r > 0 else 0.0
        sortino = round((avg_r / down_dev) * annual_factor, 2) if down_dev > 0 else 0.0
    else:
        sharpe, sortino = 0.0, 0.0

    # ★ equity_curve: 시각화용 자산 곡선 데이터 반환 (exit_time 기반 시계열, KRW)
    equity_curve_kr = []
    if pnl_series:
        _cum_kr = float(KR_DISPLAY_CAPITAL)
        for t in trade_details:
            _cum_kr += t['total_pnl']
            _et = t.get('exit_time')
            if _et is not None and pd.notna(_et):
                try:
                    equity_curve_kr.append({'time': pd.Timestamp(_et), 'equity': round(_cum_kr, 0)})
                except Exception:
                    pass

    return dict(wr=wr, pl=pl, mdd=actual_mdd, sharpe=sharpe, sortino=sortino,
                total=total, wins=wins, losses=losses, expectancy=exp,
                trade_details=trade_details, monthly_count=monthly,
                equity_curve=equity_curve_kr)  # ★ KR 자산곡선 시계열 추가

def calc_kr_asset_status(df_kr, s_kr, now):
    """국내 파트: 이벤트 발생 시점 기준 Realized PnL 추적 로직"""
    trade_details_all = s_kr.get('trade_details', [])
    window_start, window_end = get_trading_day_window(now)

    cumulative_pnl = sum(float(t.get('total_pnl', 0) or 0) for t in trade_details_all)

    # 1. 당일/당월 실현 손익 (이벤트 기반 정밀 추적)
    daily_pnl        = 0.0
    daily_commission = 0.0
    daily_trade_cnt  = 0
    monthly_pnl      = 0.0
    monthly_commission = 0.0

    if df_kr is not None and not df_kr.empty:
        CLOSE_SET = set(e.upper() for e in CLOSE_EVTS)
        FINAL_SET = set(e.upper() for e in FINAL_EXIT_EVTS)

        db_sorted = df_kr.sort_values('_dt', ascending=True)
        open_pos  = {}   # sym → {remaining, entry_price}

        for _, r in db_sorted.iterrows():
            sym = str(r.get('symbol', '') or '').strip()
            ev  = str(r.get('event',  '') or '').upper()
            dt  = r.get('_dt', pd.NaT)
            if not sym or not ev:
                continue

            if ev in ENTRY_EVTS:
                open_pos[sym] = {
                    'remaining'  : 1.0,
                    'entry_price': float(r.get('entry_price', 0) or 0),
                }
                continue

            if ev in CLOSE_SET and sym in open_pos:
                pos  = open_pos[sym]
                rem  = pos['remaining']
                ratio = min(PARTIAL_EXIT_RATIOS.get(ev, 1.0), rem) if ev in PARTIAL_EXIT_RATIOS else rem

                ep   = pos['entry_price']
                pt   = float(r.get('pnl_ticks', 0) or 0)
                qty  = max(1, int(KR_SEED_CAPITAL / ep)) if ep > 0 else 1
                pnl_krw  = pt * qty * ratio
                # 수수료: KR_COMMISSION_FIXED는 포지션 전체(왕복) 기준 → ratio만큼만 계상
                comm_krw = KR_COMMISSION_FIXED * ratio

                if pd.notna(dt):
                    if window_start <= dt < window_end:
                        daily_pnl        += pnl_krw
                        daily_commission += comm_krw
                        daily_trade_cnt  += 1
                    if dt.year == now.year and dt.month == now.month:
                        monthly_pnl        += pnl_krw
                        monthly_commission += comm_krw

                pos['remaining'] = max(0.0, rem - ratio)
                if ev in FINAL_SET:
                    del open_pos[sym]

    # 2. 월간 통계 (기존 로직 유지 - 승률/MDD 계산용)
    m_trades = [t for t in trade_details_all if pd.notna(t.get('exit_time')) and t['exit_time'].year == now.year and t['exit_time'].month == now.month]
    m_total  = len(m_trades)
    m_wins   = sum(1 for t in m_trades if t['total_pnl'] > 0)
    m_wr     = m_wins / m_total * 100 if m_total > 0 else None
    m_win_p  = [t['total_pnl'] for t in m_trades if t['total_pnl'] > 0]
    m_los_p  = [abs(t['total_pnl']) for t in m_trades if t['total_pnl'] <= 0]
    m_avg_w  = float(np.mean(m_win_p)) if m_win_p else 0.0
    m_avg_l  = float(np.mean(m_los_p)) if m_los_p else 0.0
    m_pl     = m_avg_w / m_avg_l if m_avg_l > 0 else (float('inf') if m_avg_w > 0 else None)
    m_exp    = (m_wr / 100 * m_avg_w - (1 - m_wr / 100) * m_avg_l) if m_wr is not None else 0.0
    
    if m_total > 0:
        m_ret    = np.array([t['total_pnl'] for t in m_trades]) / KR_DISPLAY_CAPITAL
        m_avg_r  = float(np.mean(m_ret))
        m_std    = float(np.std(m_ret, ddof=1)) if m_total > 1 else 0.0
        m_sharpe = round((m_avg_r / m_std) * np.sqrt(m_total), 2) if m_std > 0 else 0.0
        m_pnl_s  = [t['total_pnl'] for t in m_trades]
        m_eq     = np.array([KR_DISPLAY_CAPITAL] + list(np.cumsum(m_pnl_s) + KR_DISPLAY_CAPITAL))
        m_peak   = np.maximum.accumulate(m_eq)
        m_dd     = (m_eq - m_peak) / m_peak * 100
        m_mdd    = float(m_dd.min())
    else:
        m_sharpe, m_mdd = 0.0, 0.0

    mfe_values = []
    trade_details_today = [t for t in trade_details_all if pd.notna(t.get('exit_time')) and window_start <= pd.to_datetime(t['exit_time']) < window_end]
    for t in trade_details_today:
        ep = float(t.get('entry_price', 0) or 0)
        pt = float(t.get('pnl_ticks', 0) or 0)
        if ep > 0:
            mfe_values.append(pt / ep * 100)
    mfe_pct = max([v for v in mfe_values if v > 0], default=0.0)

    kr_account = get_live_kr_account_info()
    live_total_assets = float(kr_account.get('total_assets') or 0.0)
    display_total_assets = live_total_assets if live_total_assets > 0 else KR_DISPLAY_CAPITAL + cumulative_pnl
    account_net_pnl = display_total_assets - KR_DISPLAY_CAPITAL

    mdd_val    = s_kr.get('mdd', 0.0) or 0.0
    mdd_abs    = abs(mdd_val)
    mdd_dollar = KR_DISPLAY_CAPITAL * (mdd_abs / 100)
    recovery_profit = account_net_pnl if live_total_assets > 0 else cumulative_pnl
    recovery_factor = round(recovery_profit / mdd_dollar, 2) if mdd_dollar > 0 else (float('inf') if recovery_profit > 0 else 0.0)
    
    daily_net_pnl = daily_pnl - daily_commission
    monthly_net_pnl_calc = monthly_pnl - monthly_commission

    return dict(
        total=display_total_assets, cum_pnl=cumulative_pnl, live_total_assets=live_total_assets,
        live_total_ts=kr_account.get('timestamp'), daily_pnl=daily_net_pnl, monthly_pnl=monthly_pnl,
        monthly_net_pnl=account_net_pnl if live_total_assets > 0 else monthly_net_pnl_calc,
        monthly_commission=monthly_commission, daily_commission=daily_commission,
        daily_trade_cnt=daily_trade_cnt, mfe_pct=mfe_pct, recovery_factor=recovery_factor,
        mdd_pct=mdd_abs, expectancy=s_kr.get('expectancy', 0), m_wr=m_wr, m_pl=m_pl,
        m_mdd=m_mdd, m_exp=m_exp, m_sharpe=m_sharpe, m_total=m_total,
    )

def render_kr_asset_bar(a, s_kr=None):
    """국내주식 전용 자산바 3행 (KRW 단위)"""
    # ── 행 1: 총계 자산바
    now      = datetime.now()
    pnl_cls  = 'av-profit' if a['daily_pnl'] >= 0 else 'av-loss'
    cum_cls  = 'av-profit' if a['cum_pnl']   >= 0 else 'av-loss'
    exp_val  = a.get('expectancy', 0) or 0
    exp_str  = f"₩{exp_val:+,.0f}" if exp_val != 0 else "—"
    exp_cls  = 'av-profit' if exp_val >= 0 else 'av-loss'
    mfe_pct  = a.get('mfe_pct', 0.0) or 0.0
    mfe_cls  = 'av-profit' if mfe_pct > 0 else 'av-neutral'
    mfe_str  = f"{mfe_pct:+.2f}%" if mfe_pct != 0 else "—"
    rf       = a.get('recovery_factor', 0.0) or 0.0
    mdd_pct  = a.get('mdd_pct', 0.0) or 0.0
    rf_cls   = 'av-profit' if rf >= 2.0 else ('av-neutral' if rf >= 1.0 else 'av-loss')
    rf_str   = "∞" if rf == float('inf') else (f"{rf:.2f}" if rf != 0.0 else "—")
    # Profit Factor 계산
    _trades  = (s_kr or {}).get('trade_details', [])
    _pf_w    = sum(t['total_pnl'] for t in _trades if t['total_pnl'] > 0)
    _pf_l    = abs(sum(t['total_pnl'] for t in _trades if t['total_pnl'] < 0))
    pf_val   = _pf_w / _pf_l if _pf_l > 0 else float('inf') if _pf_w > 0 else 0.0
    pf_str   = "∞" if pf_val == float('inf') else (f"{pf_val:.2f}" if pf_val > 0 else "—")
    pf_cls   = 'av-profit' if pf_val >= 2.0 else ('av-neutral' if pf_val >= 1.0 else 'av-loss')
    live_ts  = a.get('live_total_ts')
    total_sub = f"키움 갱신: {live_ts}" if live_ts else f"누적 손익: ₩{a['cum_pnl']:+,.0f}"
    total_sub_cls = 'av-neutral' if live_ts else cum_cls
    st.markdown(f"""
    <div class="asset-bar">
      <div class="asset-cell">
        <span class="asset-lbl">🇰🇷 KR 총 운용 자산</span>
        <span class="asset-val av-total">₩{a['total']:,.0f}</span>
        <span class="asset-sub {total_sub_cls}">{total_sub}</span>
      </div>
      <div class="asset-cell">
        <span class="asset-lbl">📊 당일 순손익</span>
        <span class="asset-val {pnl_cls}">₩{a['daily_pnl']:+,.0f}</span>
        <span class="asset-sub">수수료 차감 후 실현손익</span>
      </div>
      <div class="asset-cell">
        <span class="asset-lbl">🎯 기대값 (EXPECTANCY)</span>
        <span class="asset-val {exp_cls}">{exp_str}</span>
        <span class="asset-sub">트레이딩당 평균 기대수익</span>
      </div>
      <div class="asset-cell">
        <span class="asset-lbl">📊 당월 순수익</span>
        <span class="asset-val {'av-profit' if a.get('monthly_net_pnl', 0) >= 0 else 'av-loss'}">₩{a.get('monthly_net_pnl', 0):+,.0f}</span>
        <span class="asset-sub">{now.month}월 순수익</span>
      </div>
      <div class="asset-cell">
        <span class="asset-lbl">📐 회복계수 (RECOVERY FACTOR)</span>
        <span class="asset-val {rf_cls}">{rf_str}</span>
        <span class="asset-sub">순이익 ÷ MDD (-{mdd_pct:.2f}%)</span>
      </div>
      <div class="asset-cell">
        <span class="asset-lbl">💹 수익원지수 (PROFIT FACTOR)</span>
        <span class="asset-val {pf_cls}">{pf_str}</span>
        <span class="asset-sub">총익절합 ÷ 총손절합</span>
      </div>
    </div>""", unsafe_allow_html=True)

def render_kr_part(s_kr, a_kr):
    """국내주식 KPI 3행 렌더"""
    now = datetime.now()

    # ── 행 1: 누적 총계
    wr      = f"{s_kr['wr']:.1f}%" if s_kr['wr'] is not None else "—"
    pl      = fmt_ratio_value(s_kr['pl'])
    mdd_val = s_kr.get('mdd', 0.0) or 0.0
    mdd     = f"{mdd_val:.2f}%"
    sub_all = f"{s_kr['wins']}W / {s_kr['losses']}L / 총 {s_kr['total']}트레이드"
    pl_num  = s_kr.get('pl') or 0
    wr_num  = (s_kr.get('wr') or 0) / 100
    if s_kr.get('wins', 0) > 0 and s_kr.get('losses', 0) == 0:
        rr_str = "∞"
    else:
        rr_val = pl_num * wr_num / (1 - wr_num) if (wr_num > 0 and wr_num < 1 and pl_num > 0) else 0
        rr_str = f"{rr_val:.2f}:1" if rr_val > 0 else "—"
    m_cnt   = s_kr.get('monthly_count', 0)

    st.markdown("<div class='boxtitle' style='font-size:0.68rem;color:#5a7a9a;padding:2px 4px;margin-bottom:3px'>▸ 누적 총계</div>", unsafe_allow_html=True)
    cols1 = st.columns(6)
    cards1 = [
        kpi_card("승률",        wr,                    "c2", sub_all),
        kpi_card("손익비",      pl,                    "c4", "평균 손익비"),
        kpi_card("MDD",        mdd,                    "c3", "누적대비"),
        kpi_card("샤프비율",   f"{s_kr['sharpe']:.2f}", "c6", "위험조정수익률"),
        kpi_card("월간거래횟수", f"{m_cnt}건",           "c1", f"{now.month}월 진입횟수"),
        kpi_card("리스크보상",  rr_str,                "c5", "리스크대비보상"),
    ]
    for i, c in enumerate(cols1):
        c.markdown(cards1[i], unsafe_allow_html=True)

    # ── 행 2: 월간 성과
    m_wr     = a_kr.get('m_wr')
    m_pl     = a_kr.get('m_pl')
    m_exp    = a_kr.get('m_exp', 0.0) or 0.0
    m_sharpe = a_kr.get('m_sharpe', 0.0) or 0.0
    m_total  = a_kr.get('m_total', 0)
    d_cnt    = a_kr.get('daily_trade_cnt', 0)

    m_wr_str  = f"{m_wr:.1f}%" if m_wr is not None else "—"
    m_pl_str  = fmt_ratio_value(m_pl)
    m_exp_str = f"₩{m_exp:+,.0f}" if m_exp != 0 else "—"
    m_wr_cls  = 'c2' if (m_wr or 0) >= 50 else ('c4' if (m_wr or 0) >= 40 else 'c3')
    m_pl_cls  = 'c2' if (m_pl or 0) >= 2.0 else ('c4' if (m_pl or 0) >= 1.5 else 'c3')
    m_exp_cls = 'c2' if m_exp >= 0 else 'c3'

    st.markdown("<div class='boxtitle' style='font-size:0.68rem;color:#5a7a9a;padding:2px 4px;margin-top:6px;margin-bottom:3px'>▸ 월간 성과 (日 거래정보 포함)</div>", unsafe_allow_html=True)
    cols2 = st.columns(6)
    cards2 = [
        kpi_card("승률(月)",    m_wr_str,              m_wr_cls, f"{now.month}월 {m_total}건"),
        kpi_card("손익비(月)",  m_pl_str,              m_pl_cls, f"{now.month}월 기준"),
        kpi_card("기대값(月)",  m_exp_str,              m_exp_cls, f"{now.month}월 기대수익"),
        kpi_card("샤프비율(月)",f"{m_sharpe:.2f}",     "c6",     f"{now.month}월 위험조정"),
        kpi_card("거래횟수(日)", f"{d_cnt}건",          "c1",     "당일 완결 포지션"),
        kpi_card("수수료(日)",  f"₩{a_kr.get('daily_commission', 0.0):,.0f}" if a_kr.get('daily_commission', 0.0) > 0 else "—", "c5", "당일 키움 수수료"),
    ]
    for i, c in enumerate(cols2):
        c.markdown(cards2[i], unsafe_allow_html=True)

SECTOR_MAP_DASH = {
    '반도체'  :['NVDA','AMD','AVGO','TSM','ASML','MU','INTC','AMAT','LRCX','QCOM',
                'TXN','ARM','ADI','KLAC','MCHP','ON','NXPI','MRVL','TER','ENPH'],
    '소프트웨어':['MSFT','ORCL','ADBE','CRM','NOW','INTU','SNPS','CDNS','PLTR','MDB',
                 'CRWD','TEAM','DDOG','NET','ZS','OKTA','PANW','FTNT'],
    '빅테크'  :['AAPL','GOOGL','GOOG','META','AMZN','NFLX','TSLA'],
    '핀테크'  :['V','MA','AXP','PYPL','SQ','COIN','HOOD','IBKR','DFS','AFRM'],
    '금융'    :['JPM','BAC','WFC','MS','GS','C','SCHW','BX','BLK','KKR'],
    '코인'    :['BTC','ETH','SOL','LINK','LTC','BCH','DOT','DOGE'],
    '선물'    :['NQ','ES','MNQ','MES','GC','SI','HG','CL','NG','6E','6J','ZN','ZB'],
}

def calc_monthly_report(db, year, month):
    if db is None or db.empty: return None
    from calendar import monthrange
    start_dt = datetime(year, month, 1)
    end_dt   = datetime(year, month, monthrange(year, month)[1], 23, 59, 59)
    ev_col   = 'event' if 'event' in db.columns else None
    if not ev_col: return None

    CLOSE_SET = set(e.upper() for e in CLOSE_EVTS)
    FINAL_SET = set(e.upper() for e in FINAL_EXIT_EVTS)

    entries_m = db[(db[ev_col].str.upper().isin(ENTRY_EVTS)) &
                   (db['_dt'] >= start_dt) & (db['_dt'] <= end_dt)].copy()

    # ── 포지션 단위 재생 (전체 기간 이벤트 스캔, 해당 월 내 완결 포지션만 집계)
    db_sorted = db.sort_values('_dt', ascending=True)
    open_pos = {}
    trades = []

    for _, r in db_sorted.iterrows():
        sym   = str(r.get('symbol', '') or '').strip()
        ev    = str(r.get('event',  '') or '').strip().upper()
        dt    = r.get('_dt', pd.NaT)
        if not sym or not ev:
            continue
                
        if ev in ENTRY_EVTS:
            open_pos[sym] = {
                'sym'        : sym,
                'asset_type' : str(r.get('assettype', r.get('asset_type', 'STOCK')) or 'STOCK').upper(),
                'side'       : str(r.get('side', 'LONG') or 'LONG').upper(),
                'entry_price': float(r.get('entry_price', 0) or 0),
                'grade'      : str(r.get('grade', 'C') or 'C').upper(),
                'total_pnl'  : 0.0,
                'last_event' : ev,
                'exit_time'  : dt,
                'remaining'  : 1.0,
                'exits_m'    : [],
            }
            continue

        if ev in CLOSE_SET and sym in open_pos:
            pos       = open_pos[sym]
            remaining = pos.get('remaining', 1.0)
            # ★ FIX: FINAL 이벤트는 remaining 기준으로 계산 (remaining 미반영 → 손익비 왜곡)
            if ev in PARTIAL_EXIT_RATIOS:
                ratio = min(PARTIAL_EXIT_RATIOS[ev], remaining)
            else:
                ratio = remaining
            pnl   = calc_pnl_usd(r, ratio)
            pos['total_pnl'] += pnl
            pos['last_event'] = ev
            pos['last_dt']    = dt
            pos['remaining']  = max(0.0, remaining - ratio)
            if start_dt <= dt <= end_dt:
                pos['exits_m'].append(r)

            if ev in FINAL_SET:
                # 최종 청산이 해당 월 내에 있는 경우만 집계
                if start_dt <= dt <= end_dt:
                    trades.append({
                        'sym'       : pos['sym'],
                        'grade'     : pos['grade'],
                        'asset_type': pos['asset_type'],
                        'event'     : ev,
                        'pnl'       : pos['total_pnl'],
                        'is_win'    : pos['total_pnl'] > 0,
                        'dt'        : dt,
                        'exits_m'   : pos['exits_m'],
                    })
                del open_pos[sym]

    if not trades: return None

    # gene_sep용 exits_m 재조합
    exits_m_rows = []
    for t in trades:
        exits_m_rows.extend(t.get('exits_m', []))
    exits_m = pd.DataFrame(exits_m_rows) if exits_m_rows else pd.DataFrame()

    total  = len(trades)
    wins   = sum(1 for t in trades if t['is_win'])
    losses = total - wins
    wr     = wins/total*100 if total>0 else 0
    win_p  = [t['pnl'] for t in trades if t['is_win']]
    los_p  = [abs(t['pnl']) for t in trades if not t['is_win']]
    avg_w  = float(np.mean(win_p))  if win_p  else 0
    avg_l  = float(np.mean(los_p))  if los_p  else 0
    pl_r   = avg_w/avg_l if avg_l>0 else 0
    exp    = (wr/100*avg_w) - ((1-wr/100)*avg_l)
    cum_pnl= sum(t['pnl'] for t in trades)

    evt_dist={}
    for t in trades: evt_dist[t['event']] = evt_dist.get(t['event'],0)+1
    sl_pct  = evt_dist.get('STOP_LOSS',0)/total*100  if total>0 else 0
    eod_pct = evt_dist.get('EOD_FORCE_CLOSE',0)/total*100 if total>0 else 0
    tp_cnt  = sum(v for k,v in evt_dist.items() if 'TP' in k)
    tp_pct  = tp_cnt/total*100 if total>0 else 0

    grade_stats={}
    for g in ['A','B','C']:
        gt=[t for t in trades if t['grade']==g]
        if not gt: grade_stats[g]={'total':0,'wins':0,'wr':None,'pl':None}; continue
        gw=sum(1 for t in gt if t['is_win'])
        gw_p=[t['pnl'] for t in gt if t['is_win']]
        gl_p=[abs(t['pnl']) for t in gt if not t['is_win']]
        if gw_p and gl_p and np.mean(gl_p) > 0:
            gpl = np.mean(gw_p) / np.mean(gl_p)
        else:
            gpl = 0.0   
        grade_stats[g]={'total':len(gt),'wins':gw,'wr':gw/len(gt)*100,'pl':gpl}

    asset_stats={}
    for at in ['STOCK','FUTURE','COIN']:
        at_t=[t for t in trades if t['asset_type']==at]
        if not at_t: asset_stats[at]={'total':0,'wins':0,'wr':None,'pl':None}; continue
        aw=sum(1 for t in at_t if t['is_win'])
        aw_p=[t['pnl'] for t in at_t if t['is_win']]
        al_p=[abs(t['pnl']) for t in at_t if not t['is_win']]
        if aw_p and al_p and np.mean(al_p) > 0:
            apl = np.mean(aw_p) / np.mean(al_p)
        else:
            apl = 0.0   
        asset_stats[at]={'total':len(at_t),'wins':aw,'wr':aw/len(at_t)*100,'pl':apl}

    gene_sep={}
    # v2.0: 신규 7-GENE 독립 컬럼만 대상 (기존 prefix 방식 폐기)
    GENE_COLS_V2 = ['kest_trend','g14_align','g14_score','mst_score',
                    'dsl_osc','dsl_long','sqz_val','sqz_on','sqz_momentum',
                    'g02_adx','g09_cmf','atr_val']
    gene_cols = [c for c in db.columns if c in GENE_COLS_V2]
    for gc in gene_cols:
        try:
            pnl_s=exits_m['pnl_ticks'].astype(float)
            w_pass=(exits_m.loc[pnl_s>0,gc].astype(float)>0).mean()
            l_pass=(exits_m.loc[pnl_s<=0,gc].astype(float)>0).mean()
            if not (np.isnan(w_pass) or np.isnan(l_pass)):
                gene_sep[gc]=round(w_pass-l_pass,3)
        except Exception: pass

    sector_stats={}
    for sec,syms in SECTOR_MAP_DASH.items():
        st_t=[t for t in trades if t['sym'] in syms]
        if not st_t: continue
        sw=sum(1 for t in st_t if t['is_win'])
        sector_stats[sec]={'total':len(st_t),'wins':sw,
                           'wr':sw/len(st_t)*100,'pnl':sum(t['pnl'] for t in st_t)}

    hour_stats={}
    for t in trades:
        if pd.notna(t['dt']):
            h=t['dt'].hour
            if h not in hour_stats: hour_stats[h]={'total':0,'wins':0}
            hour_stats[h]['total']+=1; hour_stats[h]['wins']+=int(t['is_win'])

    sym_pnl={}
    for t in trades: sym_pnl[t['sym']]=sym_pnl.get(t['sym'],0)+t['pnl']
    sym_rank=sorted(sym_pnl.items(),key=lambda x:x[1],reverse=True)

    blockers=[]; warnings_list=[]
    if total<100: warnings_list.append(f"표본 {total}건 (목표 100건+)")
    if wr<45:     blockers.append(f"승률 미달 {wr:.1f}%<45%")
    if exp<5:     blockers.append(f"기대값 미달 ${exp:.2f}<$5")
    a_wr=grade_stats['A']['wr']; b_wr=grade_stats['B']['wr']
    if a_wr is not None and b_wr is not None and a_wr<b_wr:
        blockers.append(f"A등급({a_wr:.1f}%)<B등급({b_wr:.1f}%) GENE역전")
    if eod_pct>15: warnings_list.append(f"EOD청산 과다 {eod_pct:.1f}%>15%")
    if sl_pct>40:  blockers.append(f"손절 과다 {sl_pct:.1f}%>40%")
    if exp<0:      blockers.append("기대값 음수 — 시스템 재검토")
    if cum_pnl<0:  warnings_list.append(f"월 누적 손실 ${cum_pnl:+,.2f}")

    if len(blockers)==0 and total>=100 and wr>=45 and exp>=5: verdict='GO'
    elif len(blockers)>=2 or exp<0: verdict='STOP'
    else: verdict='HOLD'

    return dict(year=year,month=month,total=total,wins=wins,losses=losses,
                wr=wr,pl_ratio=pl_r,exp=exp,cum_pnl=cum_pnl,avg_w=avg_w,avg_l=avg_l,
                sl_pct=sl_pct,eod_pct=eod_pct,tp_pct=tp_pct,
                evt_dist=evt_dist,grade_stats=grade_stats,asset_stats=asset_stats,
                gene_sep=gene_sep,sector_stats=sector_stats,hour_stats=hour_stats,
                sym_rank=sym_rank,blockers=blockers,warnings=warnings_list,
                verdict=verdict,entry_count=len(entries_m))

def render_part3(db):
    now = datetime.now()
    months=[]
    for i in range(6):
        d=date(now.year,now.month,1)-pd.DateOffset(months=i)
        months.append((int(d.year),int(d.month)))
    month_labels=[f"{y}년 {m}월" for y,m in months]

    c_sel,_=st.columns([2,5])
    with c_sel:
        sel_idx=st.selectbox("분석 월",range(len(months)),
                              format_func=lambda i:month_labels[i],
                              key="mr_month",label_visibility="collapsed")
    sy,sm=months[sel_idx]
    r=calc_monthly_report(db,sy,sm)

    if r is None:
        st.markdown(
            f"<div style='padding:20px;color:#2a4a6a;font-family:Share Tech Mono,"
            f"monospace;font-size:0.78rem;text-align:center'>"
            f"— {sy}년 {sm}월 청산 데이터 없음 —</div>",
            unsafe_allow_html=True); return

    if r['verdict']=='GO':
        st.markdown(
            f"<div class='verdict-go'>✅ GO — 실전 전환 검토 가능 &nbsp;|&nbsp; "
            f"승률 {r['wr']:.1f}% · 기대값 ${r['exp']:.2f} · 손익비 {r['pl_ratio']:.2f}:1</div>",
            unsafe_allow_html=True)

    wr_cls ='c2' if r['wr']>=45  else('c4' if r['wr']>=35  else 'c3')
    pl_cls ='c2' if r['pl_ratio']>=2.0 else('c4' if r['pl_ratio']>=1.5 else 'c3')
    exp_cls='c2' if r['exp']>=5  else('c4' if r['exp']>=0   else 'c3')
    pnl_cls='c2' if r['cum_pnl']>=0 else 'c3'
    kpi_cols=st.columns(6)
    for ci,(lbl,val,cls,sub) in enumerate([
        ("승률",      f"{r['wr']:.1f}%",        wr_cls,  f"{r['wins']}W/{r['losses']}L/{r['total']}건 | 기준45%+"),
        ("손익비",    f"{r['pl_ratio']:.2f}:1",  pl_cls,  f"익${r['avg_w']:.2f}/손${r['avg_l']:.2f} | 기준2.0+"),
        ("기대값",    f"${r['exp']:.2f}",        exp_cls, "건당 기대수익 | 기준$5+"),
        ("월누적PnL", f"${r['cum_pnl']:+,.2f}",  pnl_cls, f"{sy}년{sm}월 전체"),
        ("TP도달률",  f"{r['tp_pct']:.1f}%",     'c5',    f"손절{r['sl_pct']:.1f}% EOD{r['eod_pct']:.1f}%"),
        ("진입건수",  f"{r['entry_count']}건",    'c1',    f"청산완료 {r['total']}건"),
    ]):
        kpi_cols[ci].markdown(kpi_card(lbl,val,cls,sub),unsafe_allow_html=True)

    st.markdown("<div style='height:8px'></div>",unsafe_allow_html=True)

    col_a,col_b,col_c=st.columns(3)

    with col_a:
        st.markdown("<div class='mr-cell'><div class='mr-cell-title'>① 실전전환 체크리스트</div>",unsafe_allow_html=True)
        def chk(label,passed,val,warn=False):
            if passed: st.markdown(f"<div class='chk-pass'>✅ {label} {val}</div>",unsafe_allow_html=True)
            elif warn: st.markdown(f"<div class='chk-warn'>⚠️ {label} {val}</div>",unsafe_allow_html=True)
            else:      st.markdown(f"<div class='chk-fail'>❌ {label} {val}</div>",unsafe_allow_html=True)
        chk("표본 100건+", r['total']>=100,   f"{r['total']}건",       warn=r['total']>=50)
        chk("승률 45%+",   r['wr']>=45,       f"{r['wr']:.1f}%",       warn=r['wr']>=35)
        chk("기대값 $5+",  r['exp']>=5,       f"${r['exp']:.2f}",      warn=r['exp']>=0)
        a_wr=r['grade_stats']['A']['wr']; b_wr=r['grade_stats']['B']['wr']
        chk("A>B등급승률", bool(a_wr and b_wr and a_wr>b_wr),
            f"A:{a_wr:.1f}% B:{b_wr:.1f}%" if(a_wr and b_wr) else "데이터부족")
        chk("EOD<15%",     r['eod_pct']<=15,  f"{r['eod_pct']:.1f}%",  warn=r['eod_pct']<=25)
        chk("손절<40%",    r['sl_pct']<=40,   f"{r['sl_pct']:.1f}%",   warn=r['sl_pct']<=50)
        chk("손익비 2.0+", r['pl_ratio']>=2.0,f"{r['pl_ratio']:.2f}:1",warn=r['pl_ratio']>=1.5)
        chk("월PnL양수",   r['cum_pnl']>=0,   f"${r['cum_pnl']:+,.2f}")
        st.markdown("</div>",unsafe_allow_html=True)

    with col_b:
        st.markdown("<div class='mr-cell'><div class='mr-cell-title'>② 청산 사유 분포</div>",unsafe_allow_html=True)
        max_c=max(r['evt_dist'].values()) if r['evt_dist'] else 1
        for ev,cnt in sorted(r['evt_dist'].items(),key=lambda x:x[1],reverse=True):
            pct=cnt/r['total']*100
            bw=int(cnt/max_c*90)
            neg='STOP' in ev or 'LOSS' in ev or 'FORCE' in ev or 'EJECT' in ev
            col=('#ff4444' if neg else '#00e676')
            st.markdown(
                f"<div class='mr-row'>"
                f"<span class='mr-sym' style='color:{col};min-width:150px'>{ev}</span>"
                f"<div class='mr-bar' style='width:{bw}px;background:{col}'></div>"
                f"<span class='mr-val'>{cnt}건({pct:.0f}%)</span></div>",
                unsafe_allow_html=True)
        st.markdown("</div>",unsafe_allow_html=True)

    with col_c:
        st.markdown("<div class='mr-cell'><div class='mr-cell-title'>③ 등급별 · 자산군별 성과</div>",unsafe_allow_html=True)
        g_cols=st.columns(3)
        for gi,g in enumerate(['A','B','C']):
            gs=r['grade_stats'][g]
            g_wr=f"{gs['wr']:.0f}%" if gs['wr'] is not None else "—"
            g_pl=f"{gs['pl']:.2f}" if gs['pl'] is not None else "—"
            gcls='c4' if g=='A' else('c2' if g=='B' else 'c3')
            g_cols[gi].markdown(kpi_card(f"등급{g}",g_wr,gcls,f"P/L {g_pl} | {gs['total']}건"),unsafe_allow_html=True)
        st.markdown("<div style='height:6px'></div>",unsafe_allow_html=True)
        a_cols=st.columns(3)
        for ai,(at,lbl,cls) in enumerate([('STOCK','주식','c2'),('FUTURE','선물','c1'),('COIN','코인','c6')]):
            ats=r['asset_stats'][at]
            a_wr=f"{ats['wr']:.0f}%" if ats['wr'] is not None else "—"
            a_pl=f"{ats['pl']:.2f}" if ats['pl'] is not None else "—"
            a_cols[ai].markdown(kpi_card(lbl,a_wr,cls,f"P/L {a_pl} | {ats['total']}건"),unsafe_allow_html=True)
        st.markdown("</div>",unsafe_allow_html=True)

    st.markdown("<div style='height:6px'></div>",unsafe_allow_html=True)

    col_d,col_e,col_f=st.columns(3)

    with col_d:
        gene_rows = []
        if r['gene_sep']:
            max_abs = max(abs(v) for v in r['gene_sep'].values()) or 0.01   
            for gc, sv in sorted(r['gene_sep'].items(), key=lambda x: x[1], reverse=True):
                if max_abs and max_abs != 0:
                    bw = int(abs(sv) / max_abs * 80)
                else:
                    bw = 0    
                col=('#00e676' if sv>=0.15 else('#ffa726' if sv>=0.05 else '#ff4444'))
                ico='✅' if sv>=0.15 else('⚠️' if sv>=0.05 else '❌')
                gene_rows.append(
                    f"<div class='mr-row'>"
                    f"<span class='mr-sym' style='color:{col};min-width:110px'>{ico}{gc}</span>"
                    f"<div class='mr-bar' style='width:{bw}px;background:{col}'></div>"
                    f"<span class='mr-val' style='color:{col}'>{sv:+.3f}</span></div>"
                )
        else:
            gene_rows.append("<div style='color:#2a4a6a;font-size:0.7rem;padding:8px'>GENE 컬럼 데이터 부족</div>")
        st.markdown(
            "<div class='mr-cell mr-scroll-cell'>"
            "<div class='mr-cell-title'>④ GENE 지표별 분리력 (0.15+유효 / 음수제거)</div>"
            + "".join(gene_rows) +
            "</div>",
            unsafe_allow_html=True
        )

    with col_e:
        sym_rows = []
        top10=r['sym_rank'][:10]; bot5=r['sym_rank'][-5:] if len(r['sym_rank'])>10 else []
        max_abs=max((abs(v) for _,v in r['sym_rank']), default=1) or 1
        for sym,pnl in top10:
            bw=int(abs(pnl)/max_abs*80)
            col='#00e676' if pnl>=0 else '#ff4444'
            sym_rows.append(
                f"<div class='mr-row'><span class='mr-sym'>{sym}</span>"
                f"<div class='mr-bar' style='width:{bw}px;background:{col}'></div>"
                f"<span class='mr-val' style='color:{col}'>${pnl:+,.2f}</span></div>"
            )
        if bot5:
            sym_rows.append("<div style='border-top:1px dashed #1a2e45;margin:3px 0'></div>")
            for sym,pnl in bot5:
                bw=int(abs(pnl)/max_abs*80); col='#ff4444'
                sym_rows.append(
                    f"<div class='mr-row'><span class='mr-sym'>{sym}</span>"
                    f"<div class='mr-bar' style='width:{bw}px;background:{col}'></div>"
                    f"<span class='mr-val' style='color:{col}'>${pnl:+,.2f}</span></div>"
                )
        st.markdown(
            "<div class='mr-cell mr-scroll-cell'>"
            "<div class='mr-cell-title'>⑤ 종목별 PnL 랭킹</div>"
            + "".join(sym_rows) +
            "</div>",
            unsafe_allow_html=True
        )

    with col_f:
        sector_rows = []
        if r['sector_stats']:
            for sec,ss in sorted(r['sector_stats'].items(),key=lambda x:x[1]['pnl'],reverse=True):
                col='#00e676' if ss['pnl']>=0 else '#ff4444'
                sector_rows.append(
                    f"<div class='mr-row'>"
                    f"<span class='mr-sym' style='min-width:75px'>{sec}</span>"
                    f"<span style='color:#7ecfff;font-family:Share Tech Mono,monospace;"
                    f"font-size:0.67rem;min-width:45px'>{ss['wr']:.0f}%WR</span>"
                    f"<span style='color:#5a7a9a;font-size:0.67rem;min-width:30px'>{ss['total']}건</span>"
                    f"<span class='mr-val' style='color:{col}'>${ss['pnl']:+,.2f}</span></div>"
                )
        else:
            sector_rows.append("<div style='color:#2a4a6a;font-size:0.7rem;padding:8px'>데이터 없음</div>")
        sector_rows.append(
            "<div style='border-top:1px solid #1a2e45;margin:6px 0;padding-top:4px'>"
            "<span style='font-family:Orbitron,sans-serif;font-size:0.68rem;"
            "color:#b388ff;letter-spacing:2px;font-weight:700;"
            "text-shadow:0 0 10px rgba(179,136,255,0.6),0 0 22px rgba(179,136,255,0.25)'>"
            "⑦ 시간대별 승률</span></div>"
        )
        if r['hour_stats']:
            for h in sorted(r['hour_stats'].keys()):
                hs=r['hour_stats'][h]
                hwr=hs['wins']/hs['total']*100 if hs['total']>0 else 0
                col='#00e676' if hwr>=50 else('#ffa726' if hwr>=35 else '#ff4444')
                bw=int(hwr*0.7)
                sector_rows.append(
                    f"<div class='mr-row'>"
                    f"<span class='mr-sym' style='min-width:50px'>{h:02d}:xx</span>"
                    f"<div class='mr-bar' style='width:{bw}px;background:{col}'></div>"
                    f"<span class='mr-val' style='color:{col}'>{hwr:.0f}%({hs['total']}건)</span></div>"
                )
        st.markdown(
            "<div class='mr-cell mr-scroll-cell'>"
            "<div class='mr-cell-title'>⑥ 섹터별 성과</div>"
            + "".join(sector_rows) +
            "</div>",
            unsafe_allow_html=True
        )

def render_violation_warning(violations):
    if not violations: return
    items = "".join(
        f"<div class='violation-item'>⚠️ {v['sym']} @ {v['time']}"
        f"<span class='violation-reason'>{v['reason']}</span></div>"
        for v in violations
    )
    st.markdown(
        f"<div class='violation-box'><div class='violation-title'>🚨 진입 위반 감지</div>{items}</div>",
        unsafe_allow_html=True
    )

def open_html(lst):
    if not lst:
        return "<div class='hit-row' style='text-align:center;color:#2a4a6a'>— 보유 포지션 없음 —</div>"
    _at_color = {'STOCK': '#7ecfff', 'FUTURE': '#b388ff', 'COIN': '#ffa726'}
    rows = []
    for p in lst:
        side_cls  = 'sl' if p['side'] == 'LONG' else 'ss'
        side_lbl  = 'LONG' if p['side'] == 'LONG' else 'SHORT'
        g_cls     = f"g{p.get('grade','C')}"
        atype     = p.get('asset_type', 'STOCK')
        at_col    = _at_color.get(atype, '#7ecfff')
        ev_lbl    = p.get('event', 'ENTRY')
        gcnt      = p.get('gcnt', 0)
        price_val = float(p.get('price', 0) or 0)
        price_str = f"${price_val:,.2f}" if price_val > 0 else "—"
        # 신규 7-GENE 핵심 지표 표시
        kest  = int(p.get('kest_trend', 0) or 0)
        mst   = float(p.get('mst_score', 0) or 0)
        sqz   = int(p.get('sqz_momentum', 0) or 0)
        kest_str = '▲' if kest == 1 else ('▼' if kest == -1 else '—')
        kest_col = '#00e676' if kest == 1 else ('#ff4444' if kest == -1 else '#5a7a9a')
        mst_col  = '#00e676' if mst >= 58 else ('#ff4444' if mst <= 42 else '#ffe066')
        sqz_str  = '▲' if sqz == 1 else ('▼' if sqz == -1 else '—')
        sqz_col  = '#00e676' if sqz == 1 else ('#ff4444' if sqz == -1 else '#5a7a9a')
        rows.append(
            f"<div class='hit-row hl'>"
            f"<span class='hp' style='color:#00e5ff;font-weight:700'>{p['sym']}</span>"
            f" &nbsp;<span style='color:{at_col};font-size:0.67rem;font-weight:700'>{atype}</span>"
            f" &nbsp;<span class='{side_cls}'>{side_lbl}</span>"
            f" &nbsp;<span class='hp'>{price_str}</span>"
            f" &nbsp;<span class='{g_cls}'>[{p.get('grade','C')}·G{gcnt}/7]</span>"
            f"<br>"
            f"<span style='color:{kest_col};font-size:0.64rem'>KEST:{kest_str}</span>"
            f" <span style='color:{mst_col};font-size:0.64rem'>MST:{mst:.0f}</span>"
            f" <span style='color:{sqz_col};font-size:0.64rem'>SQZ:{sqz_str}</span>"
            f" &nbsp;<span class='ht'>{p.get('time','')[:16]} | {ev_lbl}</span>"
            f"</div>"
        )
    return "".join(rows)

def closed_html(lst):
    if not lst:
        return "<div class='hit-row' style='text-align:center;color:#2a4a6a'>— 종결 기록 없음 —</div>"
    _at_color = {'STOCK': '#7ecfff', 'FUTURE': '#b388ff', 'COIN': '#ffa726'}
    _ev_color = {
        'STOP_LOSS': '#ff4444', 'EOD_FORCE_CLOSE': '#ff6666',
        'FORCE_CLOSE': '#ff6666', 'PRE_EVENT_EXIT': '#ff8866',
        'SHORT_LOSS_EJECT': '#ff4444', 'SHORT_IMMED_EXIT': '#ff6644',
        'KEST_EXIT': '#ff8844',
        'TP1_30PCT': '#00e676', 'TP2_40PCT': '#00e676', 'TP3_30PCT': '#00e676',
        'TP3_TREND_END': '#00e676', 'BREAKEVEN_CUT': '#ffe066',
        'SLOPE_EXIT': '#ffa726', 'SEC_EXIT': '#ffa726',
        'PHASE1_EXIT': '#ffa726', 'PHASE2_EXIT': '#ffa726',
    }
    rows = []
    for t in lst:
        ep       = float(t.get('entry_price', 0) or 0)
        pnl_tick = float(t.get('pnl_ticks', 0) or 0)   # scaled value (부호 있음)
        # ★ FIX: total_pnl(USD) 기준으로 색상 판단 — pnl_ticks 부호만으론 SHORT 오판
        total_pnl_val = float(t.get('total_pnl', 0) or 0)
        pnl_pct  = (pnl_tick / ep * 100) if ep > 0 else 0.0
        pnl_cls  = 'ppos' if total_pnl_val > 0 else ('pneg' if total_pnl_val < 0 else 'pneu')
        pnl_str  = f"{pnl_pct:+.2f}%"
        ev       = t.get('event', '')
        ev_col   = _ev_color.get(ev, '#5a7a9a')
        atype    = t.get('asset_type', 'STOCK')
        at_col   = _at_color.get(atype, '#7ecfff')
        side_lbl = t.get('side', 'LONG')
        side_cls = 'sl' if side_lbl == 'LONG' else 'ss'
        rows.append(
            f"<div class='hit-row hs'>"
            f"<span class='hp' style='color:#00e5ff;font-weight:700'>{t['sym']}</span>"
            f" &nbsp;<span style='color:{at_col};font-size:0.67rem;font-weight:700'>{atype}</span>"
            f" &nbsp;<span class='{side_cls}'>{side_lbl}</span>"
            f" &nbsp;<span style='color:{ev_col};font-weight:700;font-size:0.67rem'>{ev}</span>"
            f" &nbsp;<span class='{pnl_cls}'>{pnl_str}</span>"
            f"<br><span class='ht'>{t.get('time','')[:16]}</span>"
            f"</div>"
        )
    return "".join(rows)


# ══════════════════════════════════════════════════
# [SECTION 9] GLOBAL BRIEFING (DB_NEWS 사용)
# ══════════════════════════════════════════════════
def news_cat_icon(cat, title):
    t = title.lower()
    if any(k in t for k in ['urgent','breaking','속보','긴급']): return '🚨'
    if any(k in t for k in ['trump','iran','war','military','nato','defense',
                             '정치','대통령','국방','외교','제재']): return '🏛️'
    if any(k in t for k in ['fed','rate','gdp','inflation','market',
                             '경제','금융','시장','금리','달러']): return '📊'
    if any(k in t for k in ['bitcoin','btc','eth','crypto','blockchain']): return '₿'
    if any(k in t for k in ['oil','opec','energy','barrel','gas','원유']): return '⛽'
    if any(k in t for k in ['culture','social','village','사회','문화']): return '🎭'
    if any(k in t for k in ['ceo','company','corp','trucking','cannabis']): return '💼'
    if 'KR' in cat: return '🇰🇷'
    return '📰'

def is_market_related(title, cat):
    keywords = ['market','oil','bitcoin','btc','fed','rate','trump','iran',
                'blockade','재무부','호르무즈','금리','달러','원유','주가','war']
    return any(k in title.lower() for k in keywords)

def render_briefing(news_df):
    st.markdown(
        "<div class='gb-ph'>◈&nbsp; 🌐 LIVE GLOBAL BRIEFING &nbsp;◈</div>",
        unsafe_allow_html=True
    )
    if news_df is None or (hasattr(news_df, 'empty') and news_df.empty):
        st.markdown(
            "<div style='padding:20px;color:#2a4a6a;font-family:Share Tech Mono,"
            "monospace;font-size:13px'>— 뉴스 없음 —</div>",
            unsafe_allow_html=True
        )
        return

    for idx, (_, row) in enumerate(news_df.iterrows()):
        title   = str(row.get('title', ''))
        cat     = str(row.get('category', row.get('source', 'UNKNOWN')))
        t_str   = str(row.get('time', ''))
        t_str   = t_str[11:19] if len(t_str) > 11 else t_str
        url     = str(row.get('url', '#')) or '#'
        raw     = str(row.get('raw_content', row.get('content', ''))) or ''
        raw     = re.sub('<[^<]+?>', '', raw)
        content_out = (raw[:600] + '...') if len(raw) > 600 else (raw or '상세 내용 없음')
        urgent   = is_market_related(title, cat)
        cat_icon = news_cat_icon(cat, title)
        tag_str  = '[URGENT]' if urgent else '[INTEL]'
        dot_char = '🔴' if urgent else '⚪'
        label = dot_char + ' ' + cat_icon + '  ' + tag_str + '  ' + t_str + ' | ' + cat + ' |  ' + title
        with st.expander(label, expanded=False):
            tag_col = '#ff3860' if urgent else '#ffd700'
            dot_col = '#ff3860' if urgent else '#607080'
            st.markdown(
                '<div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">'
                '<span style="width:9px;height:9px;border-radius:50%;background:'
                + dot_col + ';display:inline-block"></span>'
                '<span style="font-family:Share Tech Mono,monospace;font-size:12px;'
                'font-weight:700;color:' + tag_col + '">' + tag_str + '</span>'
                '<span style="font-family:Share Tech Mono,monospace;font-size:12px;'
                'color:#c0d0e0">' + t_str + ' | ' + cat + '</span>'
                '</div>'
                '<div style="font-family:Rajdhani,sans-serif;font-size:14px;'
                'color:#ffffff;line-height:1.8;padding-bottom:12px">'
                + content_out + '</div>',
                unsafe_allow_html=True
            )
            st.markdown(
                '<a href="' + url + '" target="_blank" '
                'style="display:inline-flex;align-items:center;gap:6px;'
                'border:1px solid #00e5ff;color:#00e5ff;'
                'padding:6px 18px;border-radius:3px;'
                'font-family:Share Tech Mono,monospace;font-size:11px;'
                'text-decoration:none;background:transparent">'
                '🔗&nbsp;TRACE ORIGIN (원문 추적)'
                '</a>',
                unsafe_allow_html=True
            )


# ══════════════════════════════════════════════════
# [SECTION 10] MAIN RENDERER (통합)
# ══════════════════════════════════════════════════
st.markdown("<h1>🛡️ AKROS  CORPORATE  STRATEGY  OFFICE</h1>", unsafe_allow_html=True)

@st.fragment(run_every=f"{REFRESH_SEC}s")
def main_dashboard_fragment():
    _now = datetime.now()
    window_start, window_end = get_trading_day_window(_now)

    # ── ① DB / 계좌 데이터 선취득 (sbar 렌더에 필요)
    db = load_trade_history()
    if db is not None:
        db_ok = "✅ DB 연결 (글로벌+KR)"
        cnt   = f"{len(db)}행"
        try:
            mtime_global = datetime.fromtimestamp(os.path.getmtime(DB_GLOBAL)).strftime("%H:%M:%S") if os.path.exists(DB_GLOBAL) else "N/A"
            mtime_kr     = datetime.fromtimestamp(os.path.getmtime(DB_KR)).strftime("%H:%M:%S")     if os.path.exists(DB_KR)     else "N/A"
            mtime = f"G:{mtime_global} K:{mtime_kr}"
        except Exception:
            mtime = "N/A"
    else:
        db_ok, cnt, mtime = "⚠️ DB 없음", "0행", "N/A"

    kr_account       = get_live_kr_account_info()
    kr_account_total = float(kr_account.get("total_assets") or 0.0)
    kr_account_label = (
        f"키움 총자산: ₩{kr_account_total:,.0f}"
        if kr_account_total > 0 else
        "키움 총자산: 대기"
    )

    # ── ② sbar — 타이틀 바로 아래 첫 번째 행
    st.markdown(f"""
<div class="sbar">
  <span>🕐 {_now.strftime('%Y-%m-%d %H:%M:%S')}</span>
  <span>{db_ok} · {cnt}</span>
  <span>DB 최종수정: {mtime}</span>
  <span>{kr_account_label}</span>
  <span>⏰ 기준: 06:00~익일05:00 | 청산: 04:57시작</span>
  <span>🔄 {REFRESH_SEC}초 자동갱신</span>
</div>""", unsafe_allow_html=True)

    # ── ③ 라이브스캔 배너 (sbar 바로 아래)
    scan_status = get_live_scan_status()
    render_live_scan_banner(scan_status)
    scan_kr_status = get_live_scan_kr_status()
    render_live_scan_banner(scan_kr_status, is_kr=True)

    # ── ④ 엔진 로그 박스 (2열: 해외 / 국내)
    _col_log_us, _col_log_kr = st.columns(2)
    with _col_log_us:
        render_log_box("📡 해외 엔진 로그  (Akros_Global)", LOG_GLOBAL, "logbox_us")
    with _col_log_kr:
        render_log_box("🇰🇷 국내 엔진 로그  (Akros_KR)", LOG_KR, "logbox_kr")

    # ── ④ 보유 포지션 & 종결 기록 (로그박스 바로 아래)
    # open_list / closed_list 는 db_global_only 파싱 후 채워지므로 미리 계산
    db_global_only = _safe_read_sql(DB_GLOBAL, "SELECT * FROM trade_history")
    if not db_global_only.empty:
        db_global_only.columns = [c.lower() for c in db_global_only.columns]
        db_global_only["_dt"] = pd.to_datetime(db_global_only["time"], errors="coerce")
        for _col in ['entry_price','current_price','pnl_ticks','gene_count',
                     'g02_adx','g09_cmf','atr_val',
                     'pul_main','pul_slope','pul_atr','pul_level0',
                     'kest_trend','g14_score','mst_score',
                     'dsl_osc','sqz_val','sqz_momentum']:
            if _col in db_global_only.columns:
                db_global_only[_col] = _coerce_numeric_series(db_global_only[_col])
        db_global_only = db_global_only.sort_values('_dt', ascending=False)
    else:
        db_global_only = pd.DataFrame()

    # PART1/2/자산바는 해외 전용 DB 기준
    s_all = analyze_trades(db_global_only if not db_global_only.empty else None)
    # ★ equity_curve → session_state 저장 (MARKET INTELLIGENCE 섹션 차트에서 사용)
    st.session_state['_eq_curve_us'] = s_all.get('equity_curve', [])
    trade_details_today = filter_trade_details_by_window(
        s_all.get('trade_details', []), window_start, window_end
    )

    if not db_global_only.empty:
        open_list, closed_list = get_open_closed(db_global_only, window_start, window_end)
    else:
        open_list, closed_list = [], []

    # ── 보유 포지션 & 종결 기록 렌더 (sbar·로그박스 바로 아래)
    _col_pos_l, _col_pos_r = st.columns(2)
    _lo = [r for r in open_list if r['side'] == 'LONG']
    _so = [r for r in open_list if r['side'] == 'SHORT']
    _wc = len([t for t in closed_list if t.get('is_win')])
    _lc = len([t for t in closed_list if not t.get('is_win')])
    with _col_pos_l:
        st.markdown(
            f"<div class='boxtitle'>🚀 보유 포지션 — "
            f"<span class='sl'>LONG {len(_lo)}</span> / "
            f"<span class='ss'>SHORT {len(_so)}</span></div>",
            unsafe_allow_html=True
        )
        st.markdown(f"<div class='scroll-box'>{open_html(open_list)}</div>", unsafe_allow_html=True)
    with _col_pos_r:
        st.markdown(
            f"<div class='boxtitle'>🏁 종결 기록 — "
            f"<span class='ppos'>익절 {_wc}</span> | "
            f"<span class='pneg'>손절 {_lc}</span> | "
            f"<span style='color:#a5c7e9;'>TOTAL {len(closed_list)}</span></div>",
            unsafe_allow_html=True
        )
        st.markdown(f"<div class='scroll-box'>{closed_html(closed_list)}</div>", unsafe_allow_html=True)

    violations = detect_violation_entries(db, _now)
    render_violation_warning(violations)

    # db_global_only 원본을 넘겨서 내부에서 리플레이를 돌릴 수 있도록 수정
    _asset = calc_asset_status(
        db_global_only, s_all.get('trade_details', []), open_list, s_all, _now
    )
    render_asset_bar(_asset, s_all)

    st.markdown('<div class="ph">◈  PART 1  —  통합 기준  (총계)  ◈</div>', unsafe_allow_html=True)
    render_part1(s_all, s_all.get('trade_details', []))

    st.markdown('<div class="ph p2">◈  PART 2  —  개별 기준  (누적)  ◈</div>', unsafe_allow_html=True)
    render_part2(s_all.get('trade_details', []))

    # ── 국내주식 전용 파트 (akros_kr.db)
    st.markdown('<div class="ph p2">◈  PART 2-KR  —  국내주식  (키움 / akros_kr.db)  ◈</div>', unsafe_allow_html=True)
    df_kr = _safe_read_sql(DB_KR, "SELECT * FROM trade_history")
    if not df_kr.empty:
        df_kr.columns = [c.lower() for c in df_kr.columns]
        df_kr["_dt"] = pd.to_datetime(df_kr["time"], errors="coerce")
        for _col in ['entry_price','current_price','pnl_ticks','gene_count']:
            if _col in df_kr.columns:
                df_kr[_col] = _coerce_numeric_series(df_kr[_col])
        df_kr = df_kr.sort_values('_dt', ascending=False)
        s_kr = analyze_kr_trades(df_kr)
        # ★ KR equity_curve → session_state 저장
        st.session_state['_eq_curve_kr'] = s_kr.get('equity_curve', [])
        _a_kr = calc_kr_asset_status(df_kr, s_kr, _now)
        render_kr_asset_bar(_a_kr, s_kr)
        render_kr_part(s_kr, _a_kr)
    elif kr_account_total > 0:
        s_kr = analyze_kr_trades(None)
        # ★ KR equity_curve → session_state 저장 (빈 경우)
        st.session_state['_eq_curve_kr'] = s_kr.get('equity_curve', [])
        _a_kr = calc_kr_asset_status(pd.DataFrame(), s_kr, _now)
        render_kr_asset_bar(_a_kr, s_kr)
        render_kr_part(s_kr, _a_kr)
    else:
        st.markdown(
            "<div style='padding:14px;color:#2a4a6a;font-family:Share Tech Mono,"
            "monospace;font-size:0.78rem;text-align:center'>"
            "— 국내주식 데이터 없음 (akros_kr.db 미생성 또는 Akros_KR_Live 미실행) —</div>",
            unsafe_allow_html=True
        )

    st.markdown('<div class="ph mr">◈  PART 3  —  월말 성과 리포트  ◈</div>', unsafe_allow_html=True)
    render_part3(db_global_only if not db_global_only.empty else None)

main_dashboard_fragment()

# ══════════════════════════════════════════════════
# MARKET INTELLIGENCE (argo_macro 사용)
# ══════════════════════════════════════════════════
st.markdown(
    "<div class='mi-ph'>◈&nbsp; 📈 AKROS MARKET INTELLIGENCE &nbsp;—&nbsp; Macro &amp; Valuation &nbsp;◈</div>",
    unsafe_allow_html=True
)

df_macro = get_macro_indicators(limit=30)  # argo_macro

if not df_macro.empty:
    latest_df = df_macro.sort_values('time').groupby('indicator_name').tail(1)
    cards = ""
    for _, row in latest_df.iterrows():
        try:
            change_val = float(row.get('change', 0) or 0)
        except Exception:
            change_val = 0.0
        ind_name = row['indicator_name']
        val = row['value']
        if "버핏" in ind_name or "Indicator" in ind_name:
            val_display = f"{val:,.1f}%"
        elif "q" in ind_name.lower():
            val_display = f"{val:,.3f}"
        else:
            val_display = f"{val:,.2f}"
        if change_val > 0: mod, icon = "mi-c-grn", "▲"
        elif change_val < 0: mod, icon = "mi-c-red", "▼"
        else: mod, icon = "mi-c-yel", "●"
        cards += (
            f"<div class='mi-card {mod}'>"
            f"<div class='mi-lbl'>{ind_name}</div>"
            f"<div class='mi-val'>{val_display}</div>"
            f"<div class='mi-cls'>{icon} {change_val:+.2f}%</div>"
            f"</div>"
        )
    st.markdown(f"<div class='mi-cards'>{cards}</div>", unsafe_allow_html=True)

    st.markdown(
        "<div class='chart-section-label'>"
        "◈&nbsp; 집중 분석 및 상관관계 비교 &nbsp;◈</div>",
        unsafe_allow_html=True
    )
    # ── 차트 탭: 매크로 지표 | 글로벌 자산곡선 | KR 자산곡선
    _tab_macro, _tab_eq_us, _tab_eq_kr = st.tabs(
        ["📊 매크로 지표", "📈 글로벌 자산곡선 (USD)", "🇰🇷 KR 자산곡선 (KRW)"]
    )

    # 공통 사이버펑크 레이아웃 팩토리
    def _cyberpunk_layout(title, yaxis_title="", yaxis_fmt=None):
        layout = dict(
            title=dict(
                text=title,
                font=dict(family="Share Tech Mono, monospace", size=13, color="#00e5ff"),
                x=0.01, xanchor='left',
            ),
            margin=dict(l=12, r=12, t=44, b=36),
            height=420,
            paper_bgcolor='rgba(8,13,24,0)',
            plot_bgcolor='rgba(13,24,41,0.85)',
            font=dict(family="Rajdhani, sans-serif", color="#c8d8e8", size=11),
            xaxis=dict(
                gridcolor='rgba(26,46,69,0.6)', gridwidth=1,
                linecolor='#1a2e45', tickcolor='#3a5a7a',
                tickfont=dict(color='#5a7a9a', size=10),
                showspikes=True, spikecolor='#00e5ff',
                spikethickness=1, spikedash='dot',
            ),
            yaxis=dict(
                title=yaxis_title,
                gridcolor='rgba(26,46,69,0.6)', gridwidth=1,
                linecolor='#1a2e45', tickcolor='#3a5a7a',
                tickfont=dict(color='#5a7a9a', size=10),
                tickformat=yaxis_fmt,
                showspikes=True, spikecolor='#00e5ff',
                spikethickness=1, spikedash='dot',
            ),
            hovermode='x unified',
            hoverlabel=dict(
                bgcolor='rgba(13,24,41,0.95)',
                bordercolor='#00e5ff',
                font=dict(family="Share Tech Mono, monospace", color="#c8d8e8", size=11),
            ),
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                font=dict(color='#7ecfff', size=10),
                bgcolor='rgba(0,0,0,0)',
            ),
        )
        return layout

    # ── 탭 1: 매크로 지표
    with _tab_macro:
        ind_options = sorted(df_macro['indicator_name'].unique().tolist())
        sel_ind = st.selectbox(
            label="지표 선택",
            options=ind_options,
            index=0,
            key="chart_ind_select",
            label_visibility="collapsed"
        )
        try:
            chart_data = df_macro[df_macro['indicator_name'] == sel_ind].copy()
            chart_data['time'] = pd.to_datetime(chart_data['time'], errors='coerce')
            chart_data = chart_data.dropna(subset=['time', 'value']).sort_values('time')
            if not chart_data.empty and len(chart_data) >= 2:
                import plotly.graph_objects as go
                _fig_macro = go.Figure()
                _fig_macro.add_trace(go.Scatter(
                    x=chart_data['time'], y=chart_data['value'],
                    mode='lines',
                    name=sel_ind,
                    line=dict(color='#00e5ff', width=2, shape='spline'),
                    fill='tozeroy',
                    fillcolor='rgba(0,229,255,0.06)',
                    hovertemplate='%{x|%Y-%m-%d %H:%M}<br><b>%{y:,.4f}</b><extra></extra>',
                ))
                _fig_macro.update_layout(**_cyberpunk_layout(
                    f"▸ {sel_ind}  —  Market Value & Macro Trend"))
                st.plotly_chart(_fig_macro, width='stretch')
            else:
                st.markdown(
                    "<div style='padding:20px;color:#2a4a6a;font-family:Share Tech Mono,"
                    "monospace;font-size:0.78rem;text-align:center'>"
                    f"— {sel_ind} 데이터 2건 미만 —</div>",
                    unsafe_allow_html=True)
        except Exception as _ce:
            st.markdown(
                f"<div style='color:#ff4444;font-family:Share Tech Mono,monospace;"
                f"font-size:0.72rem;padding:10px'>차트 렌더링 오류: {_ce}</div>",
                unsafe_allow_html=True)

    # ── 탭 2: 글로벌 자산곡선 (USD)
    with _tab_eq_us:
        try:
            # s_all은 main_dashboard_fragment 스코프이므로 session_state 경유
            _eq_us = st.session_state.get('_eq_curve_us', [])
            if _eq_us and len(_eq_us) >= 2:
                import plotly.graph_objects as go
                _eq_df_us = pd.DataFrame(_eq_us)
                _eq_df_us['time'] = pd.to_datetime(_eq_df_us['time'], errors='coerce')
                _eq_df_us = _eq_df_us.dropna(subset=['time', 'equity']).sort_values('time')
                _pos_mask = _eq_df_us['equity'] >= float(SEED_CAPITAL)
                _fig_eq_us = go.Figure()
                _fig_eq_us.add_trace(go.Scatter(
                    x=_eq_df_us['time'], y=_eq_df_us['equity'],
                    mode='lines',
                    name='Equity (USD)',
                    line=dict(color='#00e676', width=2, shape='linear'),
                    fill='tozeroy',
                    fillcolor='rgba(0,230,118,0.06)',
                    hovertemplate='%{x|%Y-%m-%d}<br><b>$%{y:,.2f}</b><extra></extra>',
                ))
                # SEED 기준선
                _fig_eq_us.add_hline(
                    y=float(SEED_CAPITAL),
                    line=dict(color='rgba(255,224,102,0.5)', width=1, dash='dot'),
                    annotation_text=f"Seed ${SEED_CAPITAL:,.0f}",
                    annotation_font=dict(color='#ffe066', size=10),
                )
                _fig_eq_global.update_layout(
                    autosize=True,  # Plotly 내부 충돌 방지
                    **_cyberpunk_layout("▸ GLOBAL  —  Equity Curve (USD)", yaxis_title="USD", yaxis_fmt=".2f")
                )
                st.plotly_chart(_fig_eq_global, width='stretch')
            else:
                st.markdown(
                    "<div style='padding:20px;color:#2a4a6a;font-family:Share Tech Mono,"
                    "monospace;font-size:0.78rem;text-align:center'>"
                    "— 완결 포지션 데이터 부족 (최소 2건) —</div>",
                    unsafe_allow_html=True)
        except Exception as _ce2:
            st.markdown(
                f"<div style='color:#ff4444;font-family:Share Tech Mono,monospace;"
                f"font-size:0.72rem;padding:10px'>글로벌 자산곡선 오류: {_ce2}</div>",
                unsafe_allow_html=True)

    # ── 탭 3: KR 자산곡선 (KRW)
    with _tab_eq_kr:
        try:
            _eq_kr = st.session_state.get('_eq_curve_kr', [])
            if _eq_kr and len(_eq_kr) >= 2:
                import plotly.graph_objects as go
                _eq_df_kr = pd.DataFrame(_eq_kr)
                _eq_df_kr['time'] = pd.to_datetime(_eq_df_kr['time'], errors='coerce')
                _eq_df_kr = _eq_df_kr.dropna(subset=['time', 'equity']).sort_values('time')
                _fig_eq_kr = go.Figure()
                _fig_eq_kr.add_trace(go.Scatter(
                    x=_eq_df_kr['time'], y=_eq_df_kr['equity'],
                    mode='lines',
                    name='Equity (KRW)',
                    line=dict(color='#b388ff', width=2, shape='linear'),
                    fill='tozeroy',
                    fillcolor='rgba(179,136,255,0.06)',
                    hovertemplate='%{x|%Y-%m-%d}<br><b>₩%{y:,.0f}</b><extra></extra>',
                ))
                _fig_eq_kr.add_hline(
                    y=float(KR_DISPLAY_CAPITAL),
                    line=dict(color='rgba(255,224,102,0.5)', width=1, dash='dot'),
                    annotation_text=f"기준 ₩{KR_DISPLAY_CAPITAL:,.0f}",
                    annotation_font=dict(color='#ffe066', size=10),
                )
                _fig_eq_kr.update_layout(
                    autosize=True,  # Plotly 엔진이 스트레칭 컨테이너 크기를 자동 인식하도록 강제
                    **_cyberpunk_layout("▸ KR  —  Equity Curve (KRW)", yaxis_title="KRW", yaxis_fmt=",")
                )
                st.plotly_chart(_fig_eq_kr, width='stretch')
            else:
                st.markdown(
                    "<div style='padding:20px;color:#2a4a6a;font-family:Share Tech Mono,"
                    "monospace;font-size:0.78rem;text-align:center'>"
                    "— KR 완결 포지션 데이터 부족 (최소 2건) —</div>",
                    unsafe_allow_html=True)
        except Exception as _ce3:
            st.markdown(
                f"<div style='color:#ff4444;font-family:Share Tech Mono,monospace;"
                f"font-size:0.72rem;padding:10px'>KR 자산곡선 오류: {_ce3}</div>",
                unsafe_allow_html=True)
else:
    st.info("ℹ️ 매크로 지표 데이터가 없습니다. Argo Agent(Akros_Agent.py)를 실행하여 akros_macro.db를 생성하십시오.")

# ══════════════════════════════════════════════════
# LIVE GLOBAL BRIEFING (akros_news.db)
# ══════════════════════════════════════════════════
news_df = get_global_intelligence(limit=12)
render_briefing(news_df)

# ══════════════════════════════════════════════════
# AUTO-REFRESH (fragment 내에서 자동, 여기서 추가 코드 없음)
# ══════════════════════════════════════════════════
