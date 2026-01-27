import streamlit as st
import pandas as pd
from ortools.sat.python import cp_model
from workalendar.asia import Taiwan
from datetime import date
import calendar
from streamlit_gsheets import GSheetsConnection

# --- 1. 基礎設定與連線 ---
st.set_page_config(page_title="🏥 智慧排班系統", layout="wide")

try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"❌ 雲端連線失敗，請檢查 Secrets 設定。錯誤訊息: {e}")
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
    except Exception as e:
        st.warning(f"⚠️ 讀取失敗: {e}")
        return (pd.DataFrame(columns=["姓名"]), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

# --- 2. 資料初始化 ---
if "data_loaded" not in st.session_state:
    s, p, m, l, h = load_data()
    for df, col in [(l, "開始日期"), (l, "結束日期"), (h, "日期")]:
        if not df.empty and col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    st.session_state.staff_df = s
    st.session_state.pref_data = p
    st.session_state.m_data = m
    st.session_state.leave_data = l
    st.session_state.holiday_data = h
    st.session_state.data_loaded = True

current_staff_list = sorted([n.strip() for n in st.session_state.staff_df["姓名"].tolist() if n.strip()])

# --- 3. 側邊欄 UI ---
with st.sidebar:
    st.title("⚙️ 控制面板")
    sel_year = st.selectbox("年份", [2026, 2027], index=0)
    sel_month = st.selectbox("月份", range(1, 13), index=date.today().month - 1)
    last_day_val = calendar.monthrange(sel_year, sel_month)[1]

    with st.expander("👤 1. 名單管理"):
        edited_staff = st.data_editor(st.session_state.staff_df, num_rows="dynamic", key="s_ed")
    with st.expander("🚩 2. 自訂假日"):
        edited_holiday = st.data_editor(st.session_state.holiday_data, num_rows="dynamic", key="h_ed")
    with st.expander("🏖️ 3. 人員休假"):
        edited_leave = st.data_editor(st.session_state.leave_data, num_rows="dynamic", key="l_ed")

    if st.button("💾 儲存設定並刷新"):
        conn.update(worksheet="staff", data=edited_staff.dropna(subset=["姓名"]))
        conn.update(worksheet="leaves", data=edited_leave.dropna(subset=["人員"]))
        conn.update(worksheet="custom_holidays", data=edited_holiday.dropna(subset=["日期"]))
        st.success("✅ 已同步！")
        st.rerun()

    st.subheader("👥 大夜班分組")
    g1_p = st.multiselect("第一組成員", current_staff_list)
    g1_r = st.date_input("第一組區間", [date(sel_year, sel_month, 1), date(sel_year, sel_month, 10)])
    g2_p = st.multiselect("第二組成員", current_staff_list)
    g2_r = st.date_input("第二組區間", [date(sel_year, sel_month, 11), date(sel_year, sel_month, last_day_val)])

# --- 4. 排班引擎 ---
def solve_schedule(year, month, staff_list, g1_cfg, g2_cfg, p_df, m_df, l_df, h_df):
    if not staff_list: return None, None, None, None, None, None
    cal = Taiwan()
    last_day = calendar.monthrange(year, month)[1]
    days = range(1, last_day + 1)
    model = cp_model.CpModel()
    
    x = {(e, d, s): model.NewBoolVar(f'x_{e}_{d}_{s}') for e in staff_list for d in days for s in range(2)}
    
    custom_holidays = set()
    if not h_df.empty:
        h_df['日期'] = pd.to_datetime(h_df['日期']).dt.date
        custom_holidays = {d.day for d in h_df['日期'] if d and d.year == year and d.month == month}
    holidays = [d for d in days if (not cal.is_working_day(date(year, month, d))) or (d in custom_holidays)]
    h_set, w_set = set(holidays), set(days) - set(holidays)

    for d in days:
        curr = date(year, month, d)
        dn = None
        if len(g1_cfg['p']) > 0 and g1_cfg['r'][0] <= curr <= g1_cfg['r'][1]:
            dn = g1_cfg['p'][((curr - g1_cfg['r'][0]).days // 2) % len(g1_cfg['p'])]
        elif len(g2_cfg['p']) > 0 and g2_cfg['r'][0] <= curr <= g2_cfg['r'][1]:
            dn = g2_cfg['p'][((curr - g2_cfg['r'][0]).days // 2) % len(g2_cfg['p'])]
        if dn and dn in staff_list:
            model.Add(x[(dn, d, 1)] == 1)
            model.Add(x[(dn, d, 0)] == 0)

    for d in days:
        model.Add(sum(x[(e, d, 1)] for e in staff_list) == 1)
        need = 2 if d in h_set else 1
        model.Add(sum(x[(e, d, 0)] for e in staff_list) == need)

    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    return solver, status, x, last_day, h_set, w_set

# --- 5. 畫面呈現與上傳 ---
st.header(f"🏥 {sel_year}年 {sel_month}月 班表生成")

if st.button("🚀 執行優化排班"):
    solver, status, x, last_day, h_set, w_set = solve_schedule(
        sel_year, sel_month, current_staff_list, 
        {"p": g1_p, "r": g1_r}, {"p": g2_p, "r": g2_r},
        st.session_state.pref_data, st.session_state.m_data, 
        st.session_state.leave_data, st.session_state.holiday_data
    )

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        res = []
        for d in range(1, last_day + 1):
            curr = date(sel_year, sel_month, d)
            res.append({
                "日期": f"{sel_year}-{sel_month:02d}-{d:02d}",
                "星期": week_list[curr.weekday()],
                "大夜班": "".join([e for e in current_staff_list if solver.Value(x[(e, d, 1)])]),
                "日值班": " / ".join([e for e in current_staff_list if solver.Value(x[(e, d, 0)])]),
                "班別": get_ab_shift(curr)
            })
        st.session_state.final_df = pd.DataFrame(res)
        st.session_state.h_set = h_set
        st.success("🎉 排班完成！")
    else:
        st.error("❌ 無法排班，請檢查條件。")

if "final_df" in st.session_state:
    df_res = st.session_state.final_df
    h_set = st.session_state.h_set
    target_sheet_name = f"schedule {sel_year}_{sel_month:02d}"

    st.subheader("🗓️ 預覽結果")
    st.dataframe(df_res.style.apply(lambda r: ["background-color: #FFF9C4"]*len(r) if int(r["日期"].split("-")[-1]) in h_set else [""]*len(r), axis=1))

    st.divider()
    st.subheader("📤 同步至雲端")
    st.info(f"目標分頁：`{target_sheet_name}`")
    if st.button("⬆️ 確認同步至 Google Sheets"):
        try:
            conn.update(worksheet=target_sheet_name, data=df_res)
            st.balloons()
            st.success(f"✅ 已成功上傳至分頁：{target_sheet_name}")
        except Exception as e:
            st.error(f"上傳失敗：{e}")

