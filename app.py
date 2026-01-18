import streamlit as st
import pandas as pd
from ortools.sat.python import cp_model
from workalendar.asia import Taiwan
from datetime import date
import calendar
from streamlit_gsheets import GSheetsConnection
import time

# --- 1. 基礎設定 ---
st.set_page_config(page_title="🏥 智慧排班系統", layout="wide")

all_staff = ["鄭國鳴", "林俊毅", "金弘毅", "吳宗瑋", "陳冠名", "高柏翔", "林羿旻", "洪琮幃", "吳柏毅", "楊浩宏", "葉瀚聰", "陳柏豪", "黃吉禎"]
week_list = ["禮拜一", "禮拜二", "禮拜三", "禮拜四", "禮拜五", "禮拜六", "禮拜日"]
week_map = {w: i for i, w in enumerate(week_list)}
shift_types = ["A班", "B班", "不值班"]
pref_types = ["平日", "假日", "全部"]

conn = st.connection("gsheets", type=GSheetsConnection)

def get_ab_shift(target_date):
    base_date = date(2026, 1, 1)
    delta_days = (target_date - base_date).days
    if delta_days < 0: return "未知"
    if delta_days == 0: return "B班"
    cycle_idx = (delta_days - 1) // 2
    return "A班" if cycle_idx % 2 == 0 else "B班"

def load_data():
    try:
        # 強制轉字串避免 FLOAT 轉換錯誤
        p = conn.read(worksheet="preferences", ttl=0).astype(str).replace("nan", "")
        m = conn.read(worksheet="meetings", ttl=0).astype(str).replace("nan", "")
        l = conn.read(worksheet="leaves", ttl=0).astype(str).replace("nan", "")
        return p, m, l
    except Exception as e:
        st.error(f"讀取雲端失敗: {e}")
        return [pd.DataFrame(columns=["人員", "類型", "限定班別"]), 
                pd.DataFrame(columns=["人員", "開會時間"]), 
                pd.DataFrame(columns=["人員", "開始日期", "結束日期"])]

if 'data_loaded' not in st.session_state:
    p, m, l = load_data()
    l["開始日期"] = pd.to_datetime(l["開始日期"], errors='coerce')
    l["結束日期"] = pd.to_datetime(l["結束日期"], errors='coerce')
    st.session_state.pref_data = p
    st.session_state.m_data = m
    st.session_state.leave_data = l
    st.session_state.data_loaded = True

# --- 2. UI 介面 ---
with st.sidebar:
    st.title("⚙️ 控制面板")
    sel_year = st.selectbox("年份", [2026, 2027], index=0)
    sel_month = st.selectbox("月份", range(1, 13), index=date.today().month-1)
    last_day_val = calendar.monthrange(sel_year, sel_month)[1]

    with st.expander("📝 編輯偏好"):
        edited_pref = st.data_editor(st.session_state.pref_data, num_rows="dynamic", key="p_editor",
            column_config={"人員": st.column_config.SelectboxColumn(options=all_staff, required=True)})
    
    with st.expander("📅 編輯固定會議"):
        edited_m = st.data_editor(st.session_state.m_data, num_rows="dynamic", key="m_editor",
            column_config={"人員": st.column_config.SelectboxColumn(options=all_staff, required=True)})
    
    with st.expander("🏖️ 編輯人員休假"):
        edited_leave = st.data_editor(st.session_state.leave_data, num_rows="dynamic", key="l_editor",
            column_config={
                "人員": st.column_config.SelectboxColumn(options=all_staff, required=True),
                "開始日期": st.column_config.DateColumn(format="YYYY-MM-DD", required=True),
                "結束日期": st.column_config.DateColumn(format="YYYY-MM-DD", required=True)
            })

    if st.button("💾 儲存所有設定至雲端"):
        try:
            with st.spinner("同步至雲端中..."):
                conn.update(worksheet="preferences", data=edited_pref.dropna(subset=["人員"]).astype(str).reset_index(drop=True))
                time.sleep(1)
                conn.update(worksheet="meetings", data=edited_m.dropna(subset=["人員"]).astype(str).reset_index(drop=True))
                time.sleep(1)
                df_l = edited_leave.dropna(subset=["人員"]).reset_index(drop=True)
                if not df_l.empty:
                    df_l["開始日期"] = pd.to_datetime(df_l["開始日期"]).dt.strftime('%Y-%m-%d')
                    df_l["結束日期"] = pd.to_datetime(df_l["結束日期"]).dt.strftime('%Y-%m-%d')
                    df_l = df_l[["人員", "開始日期", "結束日期"]].astype(str)
                conn.update(worksheet="leaves", data=df_l)
            st.success("✅ 同步完成！")
            st.cache_data.clear()
        except Exception as e:
            st.error(f"❌ 儲存失敗: {e}")

    st.subheader("👥 大夜班分組")
    g1_p = st.multiselect("第一組成員", all_staff, default=["鄭國鳴", "林俊毅"])
    g1_r = st.date_input("第一組區間", [date(sel_year, sel_month, 1), date(sel_year, sel_month, min(10, last_day_val))])
    g2_p = st.multiselect("第二組成員", all_staff, default=["金弘毅", "吳宗瑋"])
    g2_r = st.date_input("第二組區間", [date(sel_year, sel_month, min(11, last_day_val)), date(sel_year, sel_month, last_day_val)])

# --- 3. 排班引擎 (階梯式分配強化版) ---
def solve_schedule(year, month, g1_cfg, g2_cfg, p_df, m_df, l_df):
    cal = Taiwan()
    last_day = calendar.monthrange(year, month)[1]
    days = range(1, last_day + 1)
    model = cp_model.CpModel()
    x = {(e, d, s): model.NewBoolVar(f'x_{e}_{d}_{s}') for e in all_staff for d in days for s in range(2)}
    holidays = [d for d in days if not cal.is_working_day(date(year, month, d))]
    h_set, w_set = set(holidays), set(days) - set(holidays)

    # A. 大夜班義務邏輯
    staff_night_count = {e: 0 for e in all_staff}
    for d in days:
        curr = date(year, month, d)
        dn = None
        if len(g1_cfg['r']) == 2 and g1_cfg['r'][0] <= curr <= g1_cfg['r'][1]:
            dn = g1_cfg['p'][(curr - g1_cfg['r'][0]).days // 2 % len(g1_cfg['p'])]
        elif len(g2_cfg['r']) == 2 and g2_cfg['r'][0] <= curr <= g2_cfg['r'][1]:
            dn = g2_cfg['p'][(curr - g2_cfg['r'][0]).days // 2 % len(g2_cfg['p'])]
        if dn:
            staff_night_count[dn] += 1
            model.Add(x[(dn, d, 1)] == 1); model.Add(x[(dn, d, 0)] == 0)
            if d < last_day: model.Add(x[(dn, d+1, 0)] == 0)
    for d in days: model.Add(sum(x[(e, d, 1)] for e in all_staff) == 1)

    # B. 核心需求：階梯式公平分配 (平日與假日各別獨立計算)
    soft_penalties = []
    for e in all_staff:
        w_cnt = sum(x[(e, d, 0)] for d in w_set)
        h_cnt = sum(x[(e, d, 0)] for d in h_set)
        
        if staff_night_count[e] > 20: # 本月大夜人員免除日值班
            model.Add(w_cnt == 0); model.Add(h_cnt == 0)
        else:
            # 第一階段：每人平日/假日都要有 1 天 (極高權重)
            h1w = model.NewBoolVar(f'h1w_{e}'); model.Add(w_cnt >= 1).OnlyEnforceIf(h1w); soft_penalties.append(h1w.Not() * 1000000)
            h1h = model.NewBoolVar(f'h1h_{e}'); model.Add(h_cnt >= 1).OnlyEnforceIf(h1h); soft_penalties.append(h1h.Not() * 1000000)
            
            # 第二階段：每人平日/假日盡量達成 2 天 (中高權重)
            h2w = model.NewBoolVar(f'h2w_{e}'); model.Add(w_cnt >= 2).OnlyEnforceIf(h2w); soft_penalties.append(h2w.Not() * 500000)
            h2h = model.NewBoolVar(f'h2h_{e}'); model.Add(h_cnt >= 2).OnlyEnforceIf(h2h); soft_penalties.append(h2h.Not() * 500000)
            
            # 第三階段：如果需要第 3 天 (給予懲罰，能不排就不排)
            i3w = model.NewBoolVar(f'i3w_{e}'); model.Add(w_cnt == 3).OnlyEnforceIf(i3w); soft_penalties.append(i3w * 10000)
            i3h = model.NewBoolVar(f'i3h_{e}'); model.Add(h_cnt == 3).OnlyEnforceIf(i3h); soft_penalties.append(i3h * 10000)

        model.Add(w_cnt <= 3); model.Add(h_cnt <= 3) # 強制上限

    # C. 日值班基本約束
    for d in days: model.Add(sum(x[(e, d, 0)] for e in all_staff) == (2 if d in h_set else 1))
    for e in all_staff:
        for d in range(1, last_day): model.Add(x[(e, d, 0)] + x[(e, d+1, 0)] <= 1)

    # D. 外部設定規則
    for _, row in p_df.dropna(subset=["人員"]).iterrows():
        if row["限定班別"] == "不值班":
            target = w_set if row["類型"] == "平日" else h_set if row["類型"] == "假日" else days
            for d in target: model.Add(x[(row["人員"], d, 0)] == 0)
    for _, row in m_df.dropna(subset=["人員"]).iterrows():
        wd = week_map.get(row["開會時間"])
        if wd is not None:
            for d in days:
                if date(year, month, d).weekday() == wd: model.Add(x[(row["人員"], d, 0)] == 0)
    for _, row in l_df.dropna(subset=["人員"]).iterrows():
        if pd.notnull(row["開始日期"]) and pd.notnull(row["結束日期"]):
            sd, ed = pd.to_datetime(row["開始日期"]).date(), pd.to_datetime(row["結束日期"]).date()
            for d in days:
                if sd <= date(year, month, d) <= ed:
                    model.Add(x[(row["人員"], d, 0)] == 0); model.Add(x[(row["人員"], d, 1)] == 0)

    model.Maximize(- sum(soft_penalties))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 20.0
    return solver, solver.Solve(model), x, last_day, h_set, w_set

# --- 4. 呈現 ---
def highlight_rows(row, h_list):
    d = int(row["日期"].split('/')[-1])
    return ['background-color: #FFF9C4'] * len(row) if d in h_list else [''] * len(row)

st.header(f"🏥 {sel_year}年 {sel_month}月 智慧班表生成")
if st.button("🚀 執行優化排班"):
    solver, status, x, last_day, h_set, w_set = solve_schedule(sel_year, sel_month, {'p': g1_p, 'r': g1_r}, {'p': g2_p, 'r': g2_r}, edited_pref, edited_m, edited_leave)
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        res = []
        for d in range(1, last_day + 1):
            curr = date(sel_year, sel_month, d)
            res.append({
                "日期": f"{sel_month}/{d}", "星期": week_list[curr.weekday()],
                "大夜班": "".join([e for e in all_staff if solver.Value(x[(e, d, 1)])]),
                "日值班": " & ".join([e for e in all_staff if solver.Value(x[(e, d, 0)])]),
                "班別": get_ab_shift(curr)
            })
        st.write(pd.DataFrame(res).style.apply(highlight_rows, h_list=list(h_set), axis=1).to_html(), unsafe_allow_html=True)
        
        st.subheader("📊 本月值班負荷統計")
        stats = {e: {"平日日值": sum(solver.Value(x[(e, d, 0)]) for d in w_set), "假日日值": sum(solver.Value(x[(e, d, 0)]) for d in h_set), "大夜班": sum(solver.Value(x[(e, d, 1)]) for d in range(1, last_day+1))} for e in all_staff}
        st.write(pd.DataFrame(stats).T.to_html(), unsafe_allow_html=True)
    else:
        st.error("❌ 無法在當前限制下找到可行班表，請檢查是否太多人休假或設定不值班。")