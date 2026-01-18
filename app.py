import streamlit as st

import pandas as pd

from ortools.sat.python import cp_model

from workalendar.asia import Taiwan

from datetime import date, timedelta

import calendar



# --- 1. 基礎設定 ---

all_staff = ["鄭國鳴", "林俊毅", "金弘毅", "吳宗瑋", "陳冠名", "高柏翔", "林羿旻", "洪琮幃", "吳柏毅", "楊浩宏", "葉瀚聰", "陳柏豪", "黃吉禎"]

week_list = ["禮拜一", "禮拜二", "禮拜三", "禮拜四", "禮拜五", "禮拜六", "禮拜日"]

week_map = {w: i for i, w in enumerate(week_list)}



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



# --- 2. 側邊欄介面 ---

with st.sidebar:

    st.header("📅 排班月份設定")

    sel_year = st.selectbox("年份", [2026, 2027], index=0)

    sel_month = st.selectbox("月份", range(1, 13), index=0)

   

    st.write("---")



    # 初始化資料

    if 'pref_data' not in st.session_state:

        st.session_state.pref_data = [

            {"人員": "陳柏豪", "類型": "平日", "限定班別": "B班"},

            {"人員": "陳柏豪", "類型": "假日", "限定班別": "B班"},

            {"人員": "黃吉禎", "類型": "平日", "限定班別": "不值班"}

        ]

    if 'm_data' not in st.session_state:

        st.session_state.m_data = [

            {"人員": "高柏翔", "開會時間": "禮拜一"},

            {"人員": "高柏翔", "開會時間": "禮拜二"},

            {"人員": "林俊毅", "開會時間": "禮拜一"},

            {"人員": "金弘毅", "開會時間": "禮拜四"},

            {"人員": "吳宗瑋", "開會時間": "禮拜三"},

            {"人員": "吳柏毅", "開會時間": "禮拜一"},

            {"人員": "楊浩宏", "開會時間": "禮拜五"},

        ]

   

    # 【修復：休假區間初始化】

    # 使用 DataFrame 並強制轉換型別，避免 String/None 導致編輯器錯誤

    if 'leave_range_data' not in st.session_state:

        init_leave = pd.DataFrame([{"人員": "陳柏豪", "開始日期": None, "結束日期": None}])

        init_leave["開始日期"] = pd.to_datetime(init_leave["開始日期"])

        init_leave["結束日期"] = pd.to_datetime(init_leave["結束日期"])

        st.session_state.leave_range_data = init_leave



    st.header("💾 參數設定")

    with st.expander("📝 編輯偏好 (限定班別)"):

        p_df = st.data_editor(

            pd.DataFrame(st.session_state.pref_data),

            num_rows="dynamic", key="p_editor",

            column_config={

                "人員": st.column_config.SelectboxColumn("人員", options=all_staff, required=True),

                "類型": st.column_config.SelectboxColumn("類型", options=["平日", "假日", "不限"], required=True),

                "限定班別": st.column_config.SelectboxColumn("限定班別", options=["A班", "B班", "不值班"], required=True)

            }, use_container_width=True

        )

   

    with st.expander("📅 編輯固定會議"):

        m_df = st.data_editor(

            pd.DataFrame(st.session_state.m_data),

            num_rows="dynamic", key="m_editor",

            column_config={

                "人員": st.column_config.SelectboxColumn("人員", options=all_staff, required=True),

                "開會時間": st.column_config.SelectboxColumn("開會時間", options=week_list, required=True)

            }, use_container_width=True

        )



    # 【修復：編輯器型別相容性】

    with st.expander("🏖️ 編輯人員休假區間"):

        l_df = st.data_editor(

            st.session_state.leave_range_data, # 直接傳入正確型別的 DataFrame

            num_rows="dynamic", key="l_editor_v2",

            column_config={

                "人員": st.column_config.SelectboxColumn("人員", options=all_staff, required=True),

                "開始日期": st.column_config.DateColumn("開始日期", format="YYYY-MM-DD"),

                "結束日期": st.column_config.DateColumn("結束日期", format="YYYY-MM-DD")

            }, use_container_width=True

        )



    if st.button("💾 儲存所有設定"):

        st.session_state.pref_data = p_df.to_dict('records')

        st.session_state.m_data = m_df.to_dict('records')

        # 儲存時再次確保日期型別正確

        l_df["開始日期"] = pd.to_datetime(l_df["開始日期"])

        l_df["結束日期"] = pd.to_datetime(l_df["結束日期"])

        st.session_state.leave_range_data = l_df

        st.success("設定存檔成功")



    st.write("---")



    # --- 大夜設定 ---

    st.header("👥 第一組大夜")

    g1_p = st.multiselect("成員 1", all_staff, default=["鄭國鳴", "林俊毅"])

    col1, col2 = st.columns(2)

    with col1: g1_sm = st.selectbox("起月 1", range(1, 13), index=sel_month-1)

    with col2: g1_sd = st.selectbox("起日 1", range(1, get_last_day(sel_year, g1_sm) + 1), index=0)

    col3, col4 = st.columns(2)

    with col3: g1_em = st.selectbox("止月 1", range(1, 13), index=sel_month-1)

    with col4: g1_ed = st.selectbox("止日 1", range(1, get_last_day(sel_year, g1_em) + 1), index=9)



    st.header("👥 第二組大夜")

    g2_p = st.multiselect("成員 2", all_staff, default=["金弘毅", "吳宗瑋"])

    col5, col6 = st.columns(2)

    with col5: g2_sm = st.selectbox("起月 2", range(1, 13), index=sel_month-1)

    with col6: g2_sd = st.selectbox("起日 2", range(1, get_last_day(sel_year, g2_sm) + 1), index=10)

    col7, col8 = st.columns(2)

    with col7: g2_em = st.selectbox("止月 2", range(1, 13), index=sel_month-1)

    with col8: g2_ed = st.selectbox("止日 2", range(1, get_last_day(sel_year, g2_em) + 1), index=get_last_day(sel_year, g2_em)-1)



# --- 3. AI 引擎 ---

def solve_schedule(year, month, g1_cfg, g2_cfg, p_data, m_data, l_range_data):

    cal = Taiwan()

    last_day = get_last_day(year, month)

    days = range(1, last_day + 1)

    model = cp_model.CpModel()

   

    x = {(e, d, s): model.NewBoolVar(f'x_{e}_{d}_{s}') for e in all_staff for d in days for s in range(2)}

    holidays = [d for d in days if not cal.is_working_day(date(year, month, d))]

    h_set, w_set = set(holidays), set(days) - set(holidays)



    # A. 休假區間排除 (轉換為日期比較)

    if isinstance(l_range_data, pd.DataFrame):

        for _, row in l_range_data.iterrows():

            p, s_date, e_date = row["人員"], row["開始日期"], row["結束日期"]

            if p in all_staff and pd.notnull(s_date) and pd.notnull(e_date):

                # 轉為 date 物件進行比較

                s_dt, e_dt = s_date.date(), e_date.date()

                for d in days:

                    curr_date = date(year, month, d)

                    if s_dt <= curr_date <= e_dt:

                        model.Add(x[(p, d, 0)] == 0)

                        model.Add(x[(p, d, 1)] == 0)



    # B. 大夜邏輯

    is_night_day = {e: [False] * (last_day + 1) for e in all_staff}

    for d in days:

        curr = date(year, month, d)

        duty_n = None

        if g1_cfg['start'] <= curr <= g1_cfg['end']:

            duty_n = g1_cfg['p'][(curr - g1_cfg['start']).days // 2 % 2] if len(g1_cfg['p']) == 2 else None

        elif g2_cfg['start'] <= curr <= g2_cfg['end']:

            duty_n = g2_cfg['p'][(curr - g2_cfg['start']).days // 2 % 2] if len(g2_cfg['p']) == 2 else None

       

        if duty_n:

            model.Add(x[(duty_n, d, 1)] == 1)

            is_night_day[duty_n][d] = True

            model.Add(x[(duty_n, d, 0)] == 0)

            if d < last_day: model.Add(x[(duty_n, d+1, 0)] == 0)

            if d > 1: model.Add(x[(duty_n, d-1, 0)] == 0)

        model.Add(sum(x[(e, d, 1)] for e in all_staff) == 1)



    # C. 偏好與會議

    for row in p_data:

        p, t, s = row.get("人員"), row.get("類型"), row.get("限定班別")

        if p in all_staff:

            targets = w_set if t == "平日" else h_set if t == "假日" else set(days)

            for d in targets:

                if s == "不值班": model.Add(x[(p, d, 0)] == 0)

                elif get_ab_shift(date(year, month, d)) != s: model.Add(x[(p, d, 0)] == 0)



    for row in m_data:

        p, w = row.get("人員"), row.get("開會時間")

        if p in all_staff and w in week_map:

            for d in days:

                if date(year, month, d).weekday() == week_map[w]: model.Add(x[(p, d, 0)] == 0)



    # D. 負載均衡

    penalty_vars = []

    for e in all_staff:

        over_w = model.NewIntVar(0, 31, f'over_w_{e}')

        model.Add(sum(x[(e, d, 0)] for d in w_set) <= 2 + over_w)

        penalty_vars.append(over_w * 500)

        over_h = model.NewIntVar(0, 31, f'over_h_{e}')

        model.Add(sum(x[(e, d, 0)] for d in h_set) <= 2 + over_h)

        penalty_vars.append(over_h * 500)



    model.Minimize(sum(penalty_vars))

    for d in days:

        model.Add(sum(x[(e, d, 0)] for e in all_staff) == (2 if d in h_set else 1))

        for e in all_staff: model.Add(x[(e, d, 0)] + x[(e, d, 1)] <= 1)



    solver = cp_model.CpSolver()

    solver.parameters.max_time_in_seconds = 10.0 # 避免跑太久

    return solver, solver.Solve(model), x, last_day



# --- 4. 執行與呈現 ---

st.title("🏥 智慧排班系統")

if st.button(f"🚀 生成 {sel_month} 月班表"):

    g1_c = {'p': g1_p, 'start': date(sel_year, g1_sm, g1_sd), 'end': date(sel_year, g1_em, g1_ed)}

    g2_c = {'p': g2_p, 'start': date(sel_year, g2_sm, g2_sd), 'end': date(sel_year, g2_em, g2_ed)}

   

    solver, status, x, last_day = solve_schedule(

        sel_year, sel_month, g1_c, g2_c,

        st.session_state.pref_data,

        st.session_state.m_data,

        st.session_state.leave_range_data

    )



    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:

        st.success("✅ 生成成功！已避開休假區間。")

        res = []

        stats = {e: {"平日日值": 0, "假日日值": 0, "大夜": 0} for e in all_staff}

        cal = Taiwan()

        for d in range(1, last_day + 1):

            curr = date(sel_year, sel_month, d)

            is_h = not cal.is_working_day(curr)

            n_stf = [e for e in all_staff if solver.Value(x[(e, d, 1)])]

            d_stf = [e for e in all_staff if solver.Value(x[(e, d, 0)])]

            for e in n_stf: stats[e]["大夜"] += 1

            for e in d_stf:

                if is_h: stats[e]["假日日值"] += 1

                else: stats[e]["平日日值"] += 1

            res.append({

                "日期": f"{sel_month}/{d}",

                "星期": "一二三四五六日"[curr.weekday()],

                "大夜班": "".join(n_stf),

                "日值班": " & ".join(d_stf),

                "班別": get_ab_shift(curr)

            })

        st.table(pd.DataFrame(res))

        with st.expander("📊 點數統計"):

            st.dataframe(pd.DataFrame(stats).T)

    else:

        st.error("❌ 無法生成。請檢查是否太多人同時休假或條件衝突。")