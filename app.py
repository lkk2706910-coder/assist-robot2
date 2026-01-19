import streamlit as st
import pandas as pd
from ortools.sat.python import cp_model
from workalendar.asia import Taiwan
from datetime import date
import calendar
from streamlit_gsheets import GSheetsConnection
import time

# --- 0. Google Sheets 連線 ---

try:
    # 會自動從 secrets.toml 讀取 [connections.gsheets]
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"❌ 雲端連線失敗，請檢查 Secrets 設定。錯誤訊息: {e}")
    st.stop()

# --- 1. 基礎設定 ---

st.set_page_config(page_title="🏥 智慧排班系統", layout="wide")

all_staff = [
    "鄭國鳴", "林俊毅", "金弘毅", "吳宗瑋", "陳冠名", "高柏翔",
    "林羿旻", "洪琮幃", "吳柏毅", "楊浩宏", "葉瀚聰", "陳柏豪", "黃吉禎"
]

week_list = ["禮拜一", "禮拜二", "禮拜三", "禮拜四", "禮拜五", "禮拜六", "禮拜日"]
week_map = {w: i for i, w in enumerate(week_list)}

def get_ab_shift(target_date: date) -> str:
    """
    A/B 班判定：
    - 2026-01-01 = B班
    - 接著每兩天換一次 A/B，循環
    """
    base_date = date(2026, 1, 1)
    delta_days = (target_date - base_date).days
    if delta_days < 0:
        return "未知"
    if delta_days == 0:
        return "B班"
    cycle_idx = (delta_days - 1) // 2
    return "A班" if cycle_idx % 2 == 0 else "B班"

def load_data():
    """從 Google Sheets 讀取三個工作表，若失敗回傳空表。"""
    try:
        p = conn.read(worksheet="preferences", ttl=0).astype(str).replace("nan", "")
        m = conn.read(worksheet="meetings", ttl=0).astype(str).replace("nan", "")
        l = conn.read(worksheet="leaves", ttl=0).astype(str).replace("nan", "")
        return p, m, l
    except Exception as e:
        st.warning(f"目前無法從雲端讀取資料，請確認工作表是否存在: {e}")
        return (
            pd.DataFrame(columns=["人員", "類型", "限定班別"]),
            pd.DataFrame(columns=["人員", "開會時間"]),
            pd.DataFrame(columns=["人員", "開始日期", "結束日期"]),
        )

# 第一次載入資料
if "data_loaded" not in st.session_state:
    p, m, l = load_data()
    # 將休假日期轉為 datetime
    if not l.empty:
        l["開始日期"] = pd.to_datetime(l["開始日期"], errors="coerce")
        l["結束日期"] = pd.to_datetime(l["結束日期"], errors="coerce")
    st.session_state.pref_data = p
    st.session_state.m_data = m
    st.session_state.leave_data = l
    st.session_state.data_loaded = True

# --- 2. 側邊欄 UI ---

with st.sidebar:
    st.title("⚙️ 控制面板")

    sel_year = st.selectbox("年份", [2026, 2027], index=0)
    sel_month = st.selectbox("月份", range(1, 13), index=date.today().month - 1)
    last_day_val = calendar.monthrange(sel_year, sel_month)[1]

    # 偏好：人員 / 類型(平日/假日) / 限定班別(不值班/A班/B班)
    with st.expander("📝 編輯偏好"):
        edited_pref = st.data_editor(
            st.session_state.pref_data,
            num_rows="dynamic",
            key="p_editor",
            column_config={
                "人員": st.column_config.SelectboxColumn(options=all_staff, required=True),
                "類型": st.column_config.SelectboxColumn(
                    options=["平日", "假日"],
                    required=True
                ),
                "限定班別": st.column_config.SelectboxColumn(
                    options=["不值班", "A班", "B班"],
                    required=True
                ),
            },
        )

    # 固定會議
    with st.expander("📅 編輯固定會議"):
        edited_m = st.data_editor(
            st.session_state.m_data,
            num_rows="dynamic",
            key="m_editor",
            column_config={
                "人員": st.column_config.SelectboxColumn(options=all_staff, required=True),
                # 若「開會時間」是星期文字，可以改用下列設定
                # "開會時間": st.column_config.SelectboxColumn(options=week_list, required=True),
            },
        )

    # 休假
    with st.expander("🏖️ 編輯人員休假"):
        edited_leave = st.data_editor(
            st.session_state.leave_data,
            num_rows="dynamic",
            key="l_editor",
            column_config={
                "人員": st.column_config.SelectboxColumn(options=all_staff, required=True),
                "開始日期": st.column_config.DateColumn(
                    format="YYYY-MM-DD", required=True
                ),
                "結束日期": st.column_config.DateColumn(
                    format="YYYY-MM-DD", required=True
                ),
            },
        )

    # 儲存按鈕
    if st.button("💾 儲存所有設定至雲端"):
        try:
            with st.spinner("正在寫入雲端..."):
                # 偏好
                conn.update(
                    worksheet="preferences",
                    data=edited_pref.dropna(subset=["人員"]).astype(str).reset_index(drop=True),
                )
                time.sleep(1)

                # 會議
                conn.update(
                    worksheet="meetings",
                    data=edited_m.dropna(subset=["人員"]).astype(str).reset_index(drop=True),
                )
                time.sleep(1)

                # 休假
                df_l = edited_leave.dropna(subset=["人員"]).reset_index(drop=True)
                if not df_l.empty:
                    df_l["開始日期"] = pd.to_datetime(df_l["開始日期"]).dt.strftime(
                        "%Y-%m-%d"
                    )
                    df_l["結束日期"] = pd.to_datetime(df_l["結束日期"]).dt.strftime(
                        "%Y-%m-%d"
                    )
                    df_l = df_l[["人員", "開始日期", "結束日期"]].astype(str)
                conn.update(worksheet="leaves", data=df_l)

            st.success("✅ 已儲存至 Google Sheets")
            st.cache_data.clear()
        except Exception as e:
            st.error(f"儲存失敗，請確認是否為編輯者權限: {e}")

    # 大夜班分組
    st.subheader("👥 大夜班分組")
    g1_p = st.multiselect("第一組成員", all_staff, default=["鄭國鳴", "林俊毅"])
    g1_r = st.date_input(
        "第一組區間",
        [date(sel_year, sel_month, 1), date(sel_year, sel_month, min(10, last_day_val))],
    )
    g2_p = st.multiselect("第二組成員", all_staff, default=["金弘毅", "吳宗瑋"])
    g2_r = st.date_input(
        "第二組區間",
        [
            date(sel_year, sel_month, min(11, last_day_val)),
            date(sel_year, sel_month, last_day_val),
        ],
    )

# --- 3. 排班引擎 ---

def solve_schedule(year, month, g1_cfg, g2_cfg, p_df, m_df, l_df):
    cal = Taiwan()
    last_day = calendar.monthrange(year, month)[1]
    days = range(1, last_day + 1)

    model = cp_model.CpModel()

    # x[(人員, 日期, 班別)]，s=0 日班 / s=1 大夜
    x = {
        (e, d, s): model.NewBoolVar(f"x_{e}_{d}_{s}")
        for e in all_staff
        for d in days
        for s in range(2)
    }

    # 假日與平日
    holidays = [d for d in days if not cal.is_working_day(date(year, month, d))]
    h_set = set(holidays)
    w_set = set(days) - h_set

    # A. 大夜班固定邏輯

    staff_night_count = {e: 0 for e in all_staff}
    # 紀錄每個人在「大夜相關期間（大夜前3天 ~ 後3天）」的所有日期
    night_period_days = {e: set() for e in all_staff}

    for d in days:
        curr = date(year, month, d)
        dn = None

        # 第一組
        if (
            len(g1_cfg["p"]) > 0
            and len(g1_cfg["r"]) == 2
            and g1_cfg["r"][0] <= curr <= g1_cfg["r"][1]
        ):
            idx = ((curr - g1_cfg["r"][0]).days // 2) % len(g1_cfg["p"])
            dn = g1_cfg["p"][idx]
        # 第二組
        elif (
            len(g2_cfg["p"]) > 0
            and len(g2_cfg["r"]) == 2
            and g2_cfg["r"][0] <= curr <= g2_cfg["r"][1]
        ):
            idx = ((curr - g2_cfg["r"][0]).days // 2) % len(g2_cfg["p"])
            dn = g2_cfg["p"][idx]

        if dn:
            staff_night_count[dn] += 1

            # 大夜當日：必須上大夜，且不能上日班
            model.Add(x[(dn, d, 1)] == 1)
            model.Add(x[(dn, d, 0)] == 0)

            # 大夜前3天 ~ 後3天，全部視為「大夜相關期間」，禁止日班
            for offset in range(-3, 4):  # -3, -2, -1, 0, +1, +2, +3
                dd = d + offset
                if 1 <= dd <= last_day:
                    night_period_days[dn].add(dd)

    # 大夜相關期間（前3天~後3天），一律不能上日班（不管平日/假日）
    for e in all_staff:
        for d in night_period_days[e]:
            model.Add(x[(e, d, 0)] == 0)

    # 每天一定剛好一位大夜
    for d in days:
        model.Add(sum(x[(e, d, 1)] for e in all_staff) == 1)

    # B. 平假日分配公平（最多 3 天，1~2 天優先）

    soft_penalties = []

    for e in all_staff:
        w_cnt = sum(x[(e, d, 0)] for d in w_set)
        h_cnt = sum(x[(e, d, 0)] for d in h_set)

        if staff_night_count[e] > 20:
            # 大夜班過多的人，不再安排日班
            model.Add(w_cnt == 0)
            model.Add(h_cnt == 0)
        else:
            # 至少 1 平日
            h1w = model.NewBoolVar(f"h1w_{e}")
            model.Add(w_cnt >= 1).OnlyEnforceIf(h1w)
            soft_penalties.append(h1w.Not() * 1_000_000)

            # 至少 1 假日
            h1h = model.NewBoolVar(f"h1h_{e}")
            model.Add(h_cnt >= 1).OnlyEnforceIf(h1h)
            soft_penalties.append(h1h.Not() * 1_000_000)

            # 優先 2 平日
            h2w = model.NewBoolVar(f"h2w_{e}")
            model.Add(w_cnt >= 2).OnlyEnforceIf(h2w)
            soft_penalties.append(h2w.Not() * 100_000)

            # 優先 2 假日
            h2h = model.NewBoolVar(f"h2h_{e}")
            model.Add(h_cnt >= 2).OnlyEnforceIf(h2h)
            soft_penalties.append(h2h.Not() * 100_000)

            # 不鼓勵第 3 天
            i3w = model.NewBoolVar(f"i3w_{e}")
            model.Add(w_cnt == 3).OnlyEnforceIf(i3w)
            soft_penalties.append(i3w * 10_000)

            i3h = model.NewBoolVar(f"i3h_{e}")
            model.Add(h_cnt == 3).OnlyEnforceIf(i3h)
            soft_penalties.append(i3h * 10_000)

        # 硬限制：最多 3 天
        model.Add(w_cnt <= 3)
        model.Add(h_cnt <= 3)

    # C. 日值班規則：平日 1 人，假日 2 人

    for d in days:
        need = 2 if d in h_set else 1
        model.Add(sum(x[(e, d, 0)] for e in all_staff) == need)

    # 日班不連兩天
    for e in all_staff:
        for d in range(1, last_day):
            model.Add(x[(e, d, 0)] + x[(e, d + 1, 0)] <= 1)

    # D. 固定會議：該星期幾不能日班

    if not m_df.empty and "人員" in m_df.columns:
        for _, row in m_df.dropna(subset=["人員"]).iterrows():
            day_str = row.get("開會時間", None)
            wd = week_map.get(day_str)
            if wd is not None:
                for d in days:
                    if date(year, month, d).weekday() == wd:
                        model.Add(x[(row["人員"], d, 0)] == 0)

    # E. 休假：該日期不能排日班也不能排大夜

    if not l_df.empty and {"人員", "開始日期", "結束日期"}.issubset(l_df.columns):
        for _, row in l_df.dropna(subset=["人員"]).iterrows():
            if pd.notnull(row["開始日期"]) and pd.notnull(row["結束日期"]):
                sd = pd.to_datetime(row["開始日期"]).date()
                ed = pd.to_datetime(row["結束日期"]).date()
                for d in days:
                    cur_day = date(year, month, d)
                    if sd <= cur_day <= ed:
                        model.Add(x[(row["人員"], d, 0)] == 0)
                        model.Add(x[(row["人員"], d, 1)] == 0)

    # F. 偏好：平日 / 假日 + 不值班 / A班 / B班
    #    只限制「日班 (s=0)」，大夜 (s=1) 完全不受影響

    if not p_df.empty and {"人員", "類型", "限定班別"}.issubset(p_df.columns):
        # 可能同一個人有多筆設定（平日一筆、假日一筆），逐筆處理
        for _, row in p_df.dropna(subset=["人員", "類型", "限定班別"]).iterrows():
            person = row["人員"]
            p_type = row["類型"]       # "平日" 或 "假日"
            limit = row["限定班別"]    # "不值班" / "A班" / "B班"

            if person not in all_staff:
                continue

            # 選擇要管的日期集合
            if p_type == "平日":
                target_days = w_set
            elif p_type == "假日":
                target_days = h_set
            else:
                continue  # 其他值不處理

            # 1) 不值班：這個人對應日期的「日班」全部關掉
            if limit == "不值班":
                for d in target_days:
                    model.Add(x[(person, d, 0)] == 0)
                continue

            # 2) A班 / B班：只允許對應 A/B 班日排日班，其它班別的日班關掉
            if limit in ["A班", "B班"]:
                for d in target_days:
                    curr_date = date(year, month, d)
                    ab = get_ab_shift(curr_date)  # "A班" 或 "B班"
                    if ab != limit:
                        # 這天不是指定的 A/B → 禁止日班
                        model.Add(x[(person, d, 0)] == 0)
                continue
            # 其他值忽略

    # 目標：最小化 soft_penalties
    model.Maximize(-sum(soft_penalties))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 15.0

    status = solver.Solve(model)
    return solver, status, x, last_day, h_set, w_set

# --- 4. 表格呈現 ---

def highlight_rows(row, h_list):
    d = int(row["日期"].split("/")[-1])
    if d in h_list:
        return ["background-color: #FFF9C4"] * len(row)
    return [""] * len(row)

st.header(f"🏥 {sel_year}年 {sel_month}月 班表生成")

if st.button("🚀 執行優化排班"):
    solver, status, x, last_day, h_set, w_set = solve_schedule(
        sel_year,
        sel_month,
        {"p": g1_p, "r": g1_r},
        {"p": g2_p, "r": g2_r},
        edited_pref,
        edited_m,
        edited_leave,
    )

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # 產生每日班表
        res = []
        for d in range(1, last_day + 1):
            curr = date(sel_year, sel_month, d)
            res.append(
                {
                    "日期": f"{sel_month}/{d}",
                    "星期": week_list[curr.weekday()],
                    "大夜班": "".join(
                        [e for e in all_staff if solver.Value(x[(e, d, 1)])]
                    ),
                    "日值班": " & ".join(
                        [e for e in all_staff if solver.Value(x[(e, d, 0)])]
                    ),
                    "班別": get_ab_shift(curr),
                }
            )

        st.write(
            pd.DataFrame(res)
            .style.apply(highlight_rows, h_list=list(h_set), axis=1)
            .to_html(),
            unsafe_allow_html=True,
        )

        # 統計
        st.subheader("📊 統計")
        stats = {
            e: {
                "平日": sum(solver.Value(x[(e, d, 0)]) for d in w_set),
                "假日": sum(solver.Value(x[(e, d, 0)]) for d in h_set),
                "大夜": sum(
                    solver.Value(x[(e, d, 1)]) for d in range(1, last_day + 1)
                ),
            }
            for e in all_staff
        }
        st.write(pd.DataFrame(stats).T.to_html(), unsafe_allow_html=True)

    else:
        st.error("❌ 無法找到符合所有限制的排法。")
