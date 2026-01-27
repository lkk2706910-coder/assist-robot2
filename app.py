import streamlit as st
import pandas as pd
from ortools.sat.python import cp_model
from workalendar.asia import Taiwan
from datetime import date, datetime, timedelta
import calendar
from streamlit_gsheets import GSheetsConnection

# --- 1. 基礎設定 ---
st.set_page_config(page_title="智慧排班系統", layout="wide")

try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"❌ 雲端連線失敗: {e}")
    st.stop()

week_list = ["禮拜一", "禮拜二", "禮拜三", "禮拜四", "禮拜五", "禮拜六", "禮拜日"]
week_map = {w: i for i, w in enumerate(week_list)}

def get_ab_shift(target_date: date) -> str:
    base_date = date(2026, 1, 1)
    delta_days = (target_date - base_date).days
    if delta_days < 0: return "未知"
    if delta_days == 0: return "B班"
    cycle_idx = (delta_days - 1) // 2
    return "A班" if cycle_idx % 2 == 0 else "B班"

def load_data():
    try:
        s = conn.read(worksheet="staff", ttl=0).astype(str).replace("nan", "")
        p = conn.read(worksheet="preferences", ttl=0).astype(str).replace("nan", "")
        m = conn.read(worksheet="meetings", ttl=0).astype(str).replace("nan", "")
        l = conn.read(worksheet="leaves", ttl=0).astype(str).replace("nan", "")
        h = conn.read(worksheet="custom_holidays", ttl=0).astype(str).replace("nan", "")
        return s, p, m, l, h
    except:
        return (pd.DataFrame(columns=["姓名"]), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

# --- 2. 資料初始化 ---
if "data_loaded" not in st.session_state:
    s, p, m, l, h = load_data()
    for df, col in [(l, "開始日期"), (l, "結束日期"), (h, "日期")]:
        if not df.empty and col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    st.session_state.staff_df, st.session_state.pref_data = s, p
    st.session_state.m_data, st.session_state.leave_data = m, l
    st.session_state.holiday_data = h
    st.session_state.data_loaded = True

if "df_res" not in st.session_state: st.session_state.df_res = None

current_staff_list = sorted([n.strip() for n in st.session_state.staff_df["姓名"].tolist() if n.strip()])

# --- 3. 側邊欄 ---
with st.sidebar:
    st.title("⚙️ 控制面板")
    sel_year = st.selectbox("年份", [2026, 2027])
    sel_month = st.selectbox("月份", range(1, 13), index=date.today().month - 1)
    last_day = calendar.monthrange(sel_year, sel_month)[1]
    
    st.subheader("👥 大夜班設定")
    g1_p = st.multiselect("第一組成員", current_staff_list)
    g1_r = st.date_input("第一組區間", [date(sel_year, sel_month, 1), date(sel_year, sel_month, min(15, last_day))])
    g2_p = st.multiselect("第二組成員", current_staff_list)
    g2_r = st.date_input("第二組區間", [date(sel_year, sel_month, min(16, last_day)), date(sel_year, sel_month, last_day)])

# --- 4. 排班引擎 ---
def solve_schedule(year, month, staff_list, g1, g2, p_df, m_df, l_df, h_df):
    model = cp_model.CpModel()
    cal = Taiwan()
    days = range(1, last_day + 1)
    # x[人, 日, 班別(0:日班, 1:大夜)]
    x = {(e, d, s): model.NewBoolVar(f'x_{e}_{d}_{s}') for e in staff_list for d in days for s in range(2)}

    # 假日判定
    custom_holidays = set()
    if not h_df.empty:
        custom_holidays = {d.day for d in pd.to_datetime(h_df['日期']).dt.date if d.year == year and d.month == month}
    h_set = {d for d in days if (not cal.is_working_day(date(year, month, d))) or (d in custom_holidays)}

    # --- 核心約束 1: 假日不重複排班 ---
    # 限制每個人在假日值日班的次數上限為 1
    for e in staff_list:
        model.Add(sum(x[(e, d, 0)] for d in h_set) <= 1)

    # --- 核心約束 2: 大夜保護邏輯 (期間禁止白班 + 前後3天緩衝) ---
    for e in staff_list:
        # 第一組保護
        if g1['p'] and e in g1['p']:
            p_start, p_end = g1['r'][0] - timedelta(days=3), g1['r'][1] + timedelta(days=3)
            for d in days:
                if p_start <= date(year, month, d) <= p_end:
                    model.Add(x[(e, d, 0)] == 0)
        # 第二組保護
        if g2['p'] and e in g2['p']:
            p_start, p_end = g2['r'][0] - timedelta(days=3), g2['r'][1] + timedelta(days=3)
            for d in days:
                if p_start <= date(year, month, d) <= p_end:
                    model.Add(x[(e, d, 0)] == 0)

    # 大夜排班指派 (2天一換)
    for d in days:
        curr = date(year, month, d)
        dn = None
        if g1['p'] and g1['r'][0] <= curr <= g1['r'][1]:
            dn = g1['p'][((curr - g1['r'][0]).days // 2) % len(g1['p'])]
        elif g2['p'] and g2['r'][0] <= curr <= g2['r'][1]:
            dn = g2['p'][((curr - g2_cfg['r'][0]).days // 2) % len(g2['p'])]
        if dn: model.Add(x[(dn, d, 1)] == 1)

    # 基礎人數限制
    for d in days:
        model.Add(sum(x[(e, d, 1)] for e in staff_list) == 1)
        model.Add(sum(x[(e, d, 0)] for e in staff_list) == (2 if d in h_set else 1))

    # 禁止連值日班
    for e in staff_list:
        for d in range(1, last_day):
            model.Add(x[(e, d, 0)] + x[(e, d+1, 0)] <= 1)

    # 執行優化
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    return solver, status, x, h_set

# --- 5. 畫面呈現 ---
if st.button("🚀 執行優化排班"):
    solver, status, x, h_set = solve_schedule(sel_year, sel_month, current_staff_list, 
                                              {'p': g1_p, 'r': g1_r}, {'p': g2_p, 'r': g2_r},
                                              st.session_state.pref_data, st.session_state.m_data,
                                              st.session_state.leave_data, st.session_state.holiday_data)
    
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        res = []
        for d in range(1, last_day + 1):
            curr = date(sel_year, sel_month, d)
            res.append({
                "日期": f"{sel_month}/{d}",
                "星期": week_list[curr.weekday()],
                "大夜班": "".join([e for e in current_staff_list if solver.Value(x[(e, d, 1)])]),
                "日值班": " \ ".join([e for e in current_staff_list if solver.Value(x[(e, d, 0)])]),
                "班別": get_ab_shift(curr)
            })
        st.session_state.df_res = pd.DataFrame(res)
        st.session_state.h_set = h_set

if st.session_state.df_res is not None:
    def style_h(row):
        d = int(row["日期"].split("/")[-1])
        return ["background-color: #FFF9C4"]*5 if d in st.session_state.h_set else [""]*5
    
    st.subheader("🗓️ 排班結果明細")
    st.write(st.session_state.df_res.style.apply(style_h, axis=1).to_html(), unsafe_allow_html=True)
    
    # 這裡可以接續您的 Google Sheets 上傳按鈕...
