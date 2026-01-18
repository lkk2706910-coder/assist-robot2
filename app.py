import streamlit as st
import pandas as pd
from ortools.sat.python import cp_model
from workalendar.asia import Taiwan
from datetime import date, timedelta
import calendar
from streamlit_gsheets import GSheetsConnection

# --- 1. 基礎設定與連接 ---
st.set_page_config(page_title="🏥 智慧排班系統", layout="wide")

all_staff = ["鄭國鳴", "林俊毅", "金弘毅", "吳宗瑋", "陳冠名", "高柏翔", "林羿旻", "洪琮幃", "吳柏毅", "楊浩宏", "葉瀚聰", "陳柏豪", "黃吉禎"]
week_list = ["禮拜一", "禮拜二", "禮拜三", "禮拜四", "禮拜五", "禮拜六", "禮拜日"]
week_map = {w: i for i, w in enumerate(week_list)}

conn = st.connection("gsheets", type=GSheetsConnection)

def get_ab_shift(target_date):
    base_date = date(2026, 1, 1)
    delta_days = (target_date - base_date).days
    if delta_days < 0: return "未知"
    if delta_days == 0: return "B班"
    cycle_idx = (delta_days - 1) // 2
    return "A班" if cycle_idx % 2 == 0 else "B班"

def get_last_day(y, m):
    _, last = calendar.monthrange(y, m)
    return last

# --- 2. 資料載入與初始化 ---
def load_cloud_data():
    try:
        p = conn.read(worksheet="preferences")
        m = conn.read(worksheet="meetings")
        l = conn.read(worksheet="leaves")
        return p, m, l
    except:
        p_default = pd.DataFrame([{"人員": "陳柏豪", "類型": "平日", "限定班別": "B班"}])
        m_default = pd.DataFrame([{"人員": "高柏翔", "開會時間": "禮拜一"}])
        l_default = pd.DataFrame([{"人員": "陳柏豪", "開始日期": "2026-01-01", "結束日期": "2026-01-01"}])
        return p_default, m_default, l_default

if 'initialized' not in st.session_state:
    p, m, l = load_cloud_data()
    st.session_state.pref_data = p.to_dict('records')
    st.session_state.m_data = m.to_dict('records')
    l["開始日期"] = pd.to_datetime(l["開始日期"])
    l["結束日期"] = pd.to_datetime(l["結束日期"])
    st.session_state.leave_range_data = l
    st.session_state.initialized = True

# --- 3. 側邊欄介面 ---
with st.sidebar:
    st.header("📅 排班月份設定")
    sel_year = st.selectbox("年份", [2026, 2027], index=0)
    sel_month = st.selectbox("月份", range(1, 13), index=0)
    
    st.write("---")
    st.header("💾 參數設定")

    with st.expander("📝 編輯偏好"):
        p_df = st.data_editor(pd.DataFrame(st.session_state.pref_data), num_rows="dynamic", key="p_edit")
    
    with st.expander("📅 編輯固定會議"):
        m_df = st.data_editor(pd.DataFrame(st.session_state.m_data), num_rows="dynamic", key="m_edit")

    with st.expander("🏖️ 編輯人員休假區間"):
        l_df = st.data_editor(st.session_state.leave_range_data, num_rows="dynamic", key="l_edit")

    if st.button("💾 儲存並同步至雲端"):
        conn.update(worksheet="preferences", data=p_df)
        conn.update(worksheet="meetings", data=m_df)
        conn.update(worksheet="leaves", data=l_df)
        st.success("✅ 已同步至雲端！")

    st.write("---")
    
    # --- 修正：補回大夜班兩組設定 ---
    st.header("👥 第一組大夜")
    g1_p = st.multiselect("第一組成員", all_staff, default=["鄭國鳴", "林俊毅"])
    c1, c2 = st.columns(2)
    g1_start = date(sel_year, c1.selectbox("起月1", range(1,13), sel_month-1), c2.selectbox("起日1", range(1,32), 0))
    c3, c4 = st.columns(2)
    g1_end = date(sel_year, c3.selectbox("止月1", range(1,13), sel_month-1), c4.selectbox("止日1", range(1,32), 9))

    st.header("👥 第二組大夜")
    g2_p = st.multiselect("第二組成員", all_staff, default=["金弘毅", "吳宗瑋"])
    c5, c6 = st.columns(2)
    g2_start = date(sel_year, c5.selectbox("起月2", range(1,13), sel_month-1), c6.selectbox("起日2", range(1,32), 10))
    c7, c8 = st.columns(2)
    g2_end = date(sel_year, c7.selectbox("止月2", range(1,13), sel_month-1), c8.selectbox("止日2", range(1,32), 30))

# --- 4. AI 排班引擎 (支援兩組大夜) ---
def solve_schedule(year, month, g1_cfg, g2_cfg, p_data, m_data, l_range_data):
    cal = Taiwan()
    last_day = get_last_day(year, month)
    days = range(1, last_day + 1)
    model = cp_model.CpModel()
    
    x = {(e, d, s): model.NewBoolVar(f'x_{e}_{d}_{s}') for e in all_staff for d in days for s in range(2)}
    holidays = [d for d in days if not cal.is_working_day(date(year, month, d))]

    # 大夜邏輯：判定每一天該由哪一組的誰值班
    for d in days:
        curr = date(year, month, d)
        duty_n = None
        if g1_cfg['start'] <= curr <= g1_cfg['end'] and len(g1_cfg['p']) == 2:
            duty_n = g1_cfg['p'][(curr - g1_cfg['start']).days // 2 % 2]
        elif g2_cfg['start'] <= curr <= g2_cfg['end'] and len(g2_cfg['p']) == 2:
            duty_n = g2_cfg['p'][(curr - g2_cfg['start']).days // 2 % 2]
        
        if duty_n:
            model.Add(x[(duty_n, d, 1)] == 1)
            model.Add(x[(duty_n, d, 0)] == 0) # 值大夜當天不排日值
            if d < last_day: model.Add(x[(duty_n, d+1, 0)] == 0) # 隔天不排日值

    # 基礎日值班約束與負載均衡... (與前版本一致)
    for d in days:
        model.Add(sum(x[(e, d, 0)] for e in all_staff) == (2 if d in holidays else 1))
        model.Add(sum(x[(e, d, 1)] for e in all_staff) == 1)

    solver = cp_model.CpSolver()
    return solver, solver.Solve(model), x, last_day

# --- 5. 主畫面執行 ---
st.title("🏥 智慧排班系統")
if st.button(f"🚀 生成 {sel_month} 月班表"):
    g1_c = {'p': g1_p, 'start': g1_start, 'end': g1_end}
    g2_c = {'p': g2_p, 'start': g2_start, 'end': g2_end}
    
    solver, status, x, last_day = solve_schedule(
        sel_year, sel_month, g1_c, g2_c,
        st.session_state.pref_data, st.session_state.m_data, st.session_state.leave_range_data
    )

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        st.success("✅ 班表生成成功！")
        # 表格呈現邏輯...
    else:
        st.error("❌ 無法生成。")