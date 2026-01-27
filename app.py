import streamlit as st
import pandas as pd
from ortools.sat.python import cp_model
from workalendar.asia import Taiwan
from datetime import date, datetime
import calendar
from streamlit_gsheets import GSheetsConnection
import time

# --- 1. 基礎設定與連線 ---
st.set_page_config(page_title="智慧排班系統", layout="wide")

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

# 初始化排班結果快取
if "df_res" not in st.session_state:
    st.session_state.df_res = None
if "df_stats" not in st.session_state:
    st.session_state.df_stats = None
if "h_set" not in st.session_state:
    st.session_state.h_set = set()

current_staff_list = sorted([n.strip() for n in st.session_state.staff_df["姓名"].tolist() if n.strip()])

# --- 3. 側邊欄 UI ---
with st.sidebar:
    st.title("⚙️ 控制面板")
    sel_year = st.selectbox("年份", [2026, 2027], index=0)
    sel_month = st.selectbox("月份", range(1, 13), index=date.today().month - 1)
    last_day_val = calendar.monthrange(sel_year, sel_month)[1]

    with st.expander("👤 1. 名單管理"):
        edited_staff = st.data_editor(st.session_state.staff_df, num_rows="dynamic", key="s_ed")

    with st.expander("🚩 2. 自訂假日 (2人值班)"):
        edited_holiday = st.data_editor(st.session_state.holiday_data, num_rows="dynamic", key="h_ed",
                                       column_config={"日期": st.column_config.DateColumn()})

    with st.expander("📝 3. 編輯偏好"):
        edited_pref = st.data_editor(st.session_state.pref_data, num_rows="dynamic", key="p_ed",
            column_config={
                "人員": st.column_config.SelectboxColumn(options=current_staff_list),
                "類型": st.column_config.SelectboxColumn(options=["平日", "假日"]),
                "限定班別": st.column_config.SelectboxColumn(options=["不值班", "A班", "B班"])
            })

    with st.expander("📅 4. 固定會議"):
        edited_m = st.data_editor(st.session_state.m_data, num_rows="dynamic", key="m_ed",
            column_config={
                "人員": st.column_config.SelectboxColumn(options=current_staff_list),
                "開會時間": st.column_config.SelectboxColumn(options=week_list)
            })

    with st.expander("🏖️ 5. 人員休假"):
        edited_leave = st.data_editor(st.session_state.leave_data, num_rows="dynamic", key="l_ed",
            column_config={
                "人員": st.column_config.SelectboxColumn(options=current_staff_list),
                "開始日期": st.column_config.DateColumn(),
                "結束日期": st.column_config.DateColumn()
            })

    if st.button("💾 儲存設定並刷新"):
        try:
            with st.spinner("同步中..."):
                conn.update(worksheet="staff", data=edited_staff.dropna(subset=["姓名"]).reset_index(drop=True))
                conn.update(worksheet="preferences", data=edited_pref.dropna(subset=["人員"]).reset_index(drop=True))
                conn.update(worksheet="meetings", data=edited_m.dropna(subset=["人員"]).reset_index(drop=True))
                l_save = edited_leave.copy().dropna(subset=["人員"])
                if not l_save.empty:
                    l_save["開始日期"] = l_save["開始日期"].astype(str)
                    l_save["結束日期"] = l_save["結束日期"].astype(str)
                conn.update(worksheet="leaves", data=l_save.reset_index(drop=True))
                h_save = edited_holiday.copy().dropna(subset=["日期"])
                if not h_save.empty:
                    h_save["日期"] = h_save["日期"].astype(str)
                conn.update(worksheet="custom_holidays", data=h_save.reset_index(drop=True))
                st.success("✅ 已儲存！")
                st.cache_data.clear()
                st.rerun()
        except Exception as e:
            st.error(f"儲存失敗: {e}")

    st.subheader("👥 大夜班分組")
    g1_p = st.multiselect("第一組成員 (2天一換)", current_staff_list)
    g1_r = st.date_input("第一組區間", [date(sel_year, sel_month, 1), date(sel_year, sel_month, min(10, last_day_val))])
    g2_p = st.multiselect("第二組成員 (2天一換)", current_staff_list)
    g2_r = st.date_input("第二組區間", [date(sel_year, sel_month, min(11, last_day_val)), date(sel_year, sel_month, last_day_val)])

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

    # 大夜邏輯
    staff_night_count = {e: 0 for e in staff_list}
    for d in days:
        curr = date(year, month, d)
        dn = None
        if len(g1_cfg['p']) > 0 and len(g1_cfg['r']) == 2 and g1_cfg['r'][0] <= curr <= g1_cfg['r'][1]:
            dn = g1_cfg['p'][((curr - g1_cfg['r'][0]).days // 2) % len(g1_cfg['p'])]
        elif len(g2_cfg['p']) > 0 and len(g2_cfg['r']) == 2 and g2_cfg['r'][0] <= curr <= g2_cfg['r'][1]:
            dn = g2_cfg['p'][((curr - g2_cfg['r'][0]).days // 2) % len(g2_cfg['p'])]
        if dn and dn in staff_list:
            staff_night_count[dn] += 1
            model.Add(x[(dn, d, 1)] == 1)
            model.Add(x[(dn, d, 0)] == 0)
    
    for d in days: model.Add(sum(x[(e, d, 1)] for e in staff_list) == 1)
    for d in days:
        need = 2 if d in h_set else 1
        model.Add(sum(x[(e, d, 0)] for e in staff_list) == need)

    for e in staff_list:
        for d in range(1, last_day):
            model.Add(x[(e, d, 0)] + x[(e, d+1, 0)] <= 1)
        emp_m = m_df[m_df["人員"] == e]
        for _, row in emp_m.iterrows():
            wd = week_map.get(row["開會時間"])
            if wd is not None:
                for d in days:
                    if date(year, month, d).weekday() == wd: model.Add(x[(e, d, 0)] == 0)
        emp_l = l_df[l_df["人員"] == e]
        for _, row in emp_l.iterrows():
            if not row["開始日期"] or not row["結束日期"]: continue
            sd, ed = row["開始日期"], row["結束日期"]
            for d in days:
                if sd <= date(year, month, d) <= ed:
                    model.Add(x[(e, d, 0)] == 0); model.Add(x[(e, d, 1)] == 0)
        emp_p = p_df[p_df["人員"] == e]
        for _, row in emp_p.iterrows():
            target_days = w_set if row["類型"] == "平日" else h_set
            for d in target_days:
                if row["限定班別"] == "不值班": model.Add(x[(e, d, 0)] == 0)
                elif row["限定班別"] in ["A班", "B班"]:
                    if get_ab_shift(date(year, month, d)) != row["限定班別"]:
                        model.Add(x[(e, d, 0)] == 0)

    soft_penalties = []
    for e in staff_list:
        if staff_night_count[e] < 15:
            w_cnt = sum(x[(e, d, 0)] for d in w_set)
            h_cnt = sum(x[(e, d, 0)] for d in h_set)
            for goal, weight in [(1, 5000), (2, 500)]:
                b_w = model.NewBoolVar(f"w_{e}_{goal}")
                model.Add(w_cnt >= goal).OnlyEnforceIf(b_w)
                soft_penalties.append(b_w.Not() * weight)
                b_h = model.NewBoolVar(f"h_{e}_{goal}")
                model.Add(h_cnt >= goal).OnlyEnforceIf(b_h)
                soft_penalties.append(b_h.Not() * weight)

    model.Maximize(-sum(soft_penalties))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 15.0
    return solver, solver.Solve(model), x, last_day, h_set, w_set

# --- 5. 主畫面與顯示邏輯 ---
st.header(f"🏥 {sel_year}年 {sel_month}月 班表生成系統")

if not current_staff_list:
    st.info("💡 請先在左側『名單管理』填入人員並儲存。")
else:
    # 第一步：觸發排班計算
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
                    "日期": f"{sel_month}/{d}",
                    "星期": week_list[curr.weekday()],
                    "大夜班": "".join([e for e in current_staff_list if solver.Value(x[(e, d, 1)])]),
                    "日值班": " \ ".join([e for e in current_staff_list if solver.Value(x[(e, d, 0)])]),
                    "班別": get_ab_shift(curr)
                })
            
            stats = [{
                "人員": e,
                "平日值班": sum(solver.Value(x[(e, d, 0)]) for d in w_set),
                "假日值班": sum(solver.Value(x[(e, d, 0)]) for d in h_set),
                "大夜總數": sum(solver.Value(x[(e, d, 1)]) for d in range(1, last_day+1))
            } for e in current_staff_list]

            # 將結果存入快取，避免點擊上傳按鈕時資料消失
            st.session_state.df_res = pd.DataFrame(res)
            st.session_state.df_stats = pd.DataFrame(stats)
            st.session_state.h_set = h_set
            st.success("✅ 排班生成完成！")
        else:
            st.error("❌ 找不到可行方案。請檢查休假或會議是否過於集中。")
            st.session_state.df_res = None

    # 第二步：顯示已生成的排班結果與上傳按鈕
    if st.session_state.df_res is not None:
        df_res = st.session_state.df_res
        df_stats = st.session_state.df_stats
        h_set = st.session_state.h_set

        def highlight_holiday(row):
            day_num = int(row["日期"].split("/")[-1])
            return ["background-color: #FFF9C4"] * len(row) if day_num in h_set else [""] * len(row)

        st.subheader("🗓️ 排班結果明細")
        st.write(df_res.style.apply(highlight_holiday, axis=1).to_html(), unsafe_allow_html=True)
        
        st.subheader("📊 本月統計")
        st.dataframe(df_stats, use_container_width=True)

        # --- 雲端上傳功能 ---
        st.divider()
        sheet_title = f"{sel_year}年{sel_month}月班表_{datetime.now().strftime('%m%d_%H%M')}"
        
        if st.button("📤 一鍵同步班表與統計至 Google Sheets"):
            try:
                with st.spinner("正在整合資料並建立工作表..."):
                    # 準備合併資料
                    # 建立空行與統計標題行 (確保欄位數量與 df_res 相同為 5 欄)
                    empty_sep = pd.DataFrame([[""] * 5], columns=df_res.columns)
                    stat_header = pd.DataFrame([["--- 本月出勤統計 ---", "", "", "", ""]], columns=df_res.columns)
                    
                    # 格式化統計表以符合合併寬度
                    df_stats_aligned = df_stats.copy()
                    # 將統計表的 4 欄對應到明細表的前 4 欄
                    df_stats_aligned.columns = df_res.columns[:4]
                    
                    # 拼接所有 DataFrame
                    combined_df = pd.concat([df_res, empty_sep, stat_header, df_stats_aligned], ignore_index=True)
                    
                    # 呼叫 streamlit-gsheets 的 create 方法
                    conn.create(worksheet=sheet_title, data=combined_df)
                    st.success(f"✅ 上傳成功！工作表名稱為：{sheet_title}")
                    
            except Exception as e:
                st.error(f"上傳過程發生錯誤: {e}")
        st.divider()
