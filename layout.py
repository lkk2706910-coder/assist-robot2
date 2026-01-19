import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import math
from PIL import Image, ImageTk

# ----------------- 1. 幾何座標與 Layout 設定 -----------------
CANVAS_WIDTH, CANVAS_HEIGHT = 600, 750 
WAFER_R = 45 

WAFER_POS = {
    "A2": (245, 55),  "A1": (355, 55),  
    "B1": (135, 165), "B2": (135, 275),
    "C2": (465, 165), "C1": (465, 275), 
    "LL1": (200, 385), "LL2": (400, 385),
    "CS": (300, 515), 
    "CA": (150, 670), "CB": (250, 670), "CC": (350, 670), "CD": (450, 670),
}

MODULE_BOXES = {
    "CHA": (190, 0, 410, 110), 
    "CHB": (80, 110, 190, 330), 
    "CHC": (410, 110, 520, 330),
    "MF": (190, 110, 410, 330), 
    "LL": (80, 330, 520, 440), 
    "Cooling": (250, 440, 350, 590),
    "CassA": (100, 590, 200, 720), "CassB": (200, 590, 300, 720), 
    "CassC": (300, 590, 400, 720), "CassD": (400, 590, 500, 720),
}

MODULE_LABEL_POS = {
    "CHA": (300, 20), "CHB": (135, 220), "CHC": (465, 220),
    "MF": (300, 220), "LL": (300, 350), "Cooling": (300, 460),
    "CassA": (150, 600), "CassB": (250, 600), "CassC": (350, 600), "CassD": (450, 600),
}

# ----------------- 2. 狀態管理與邏輯引擎 -----------------
current_side = "S1"
base_angle = 0 
wafer_img_mgr = {"original": None, "tk_refs": {}}

def get_full_path(cass_name, side, station):
    path = [f"C{cass_name}"]
    if (cass_name in ("A", "B") and side == "S2") or (cass_name in ("C", "D") and side == "S1"):
        path.append("CS")
    path.append("LL1" if side == "S1" else "LL2")
    if station != "LL":
        target = {"CHA":"A", "CHB":"B", "CHC":"C"}[station]
        path.append(f"{target}{'1' if side == 'S1' else '2'}")
    return path

def get_node_angle(node_name, cass_name, side, start_angle):
    if node_name in ["CA", "CB", "CC", "CD"]: return start_angle % 360
    rules = {}
    if cass_name in ("A", "B"):
        if side == "S1": rules = {"LL1": 210, "A1": 30, "B1": 300, "C1": 120, "CS": 0}
        else: rules = {"CS": 300, "LL2": 0, "A2": 180, "B2": 90, "C2": 270}
    else:
        if side == "S1": rules = {"CS": 30, "LL1": 0, "A1": 180, "B1": 90, "C1": 270}
        else: rules = {"LL2": 150, "A2": 330, "B2": 240, "C2": 60, "CS": 0}
    offset = rules.get(node_name, 0)
    return (offset + start_angle) % 360

# ----------------- 3. 繪圖核心 -----------------
def draw_layout(canvas, station_name, selected_cass):
    canvas.delete("all")
    for name, (x1, y1, x2, y2) in MODULE_BOXES.items():
        canvas.create_rectangle(x1, y1, x2, y2, outline="#CCCCCC")
        tx, ty = MODULE_LABEL_POS.get(name, ((x1+x2)//2, y1+15))
        canvas.create_text(tx, ty, text=name, fill="blue", font=("Arial", 9, "bold"))

    full_path = get_full_path(selected_cass, current_side, station_name)
    wafer_img_mgr["tk_refs"] = {}

    for name, (cx, cy) in WAFER_POS.items():
        angle = get_node_angle(name, selected_cass, current_side, base_angle)
        display_angle = (180 + angle) % 360
        is_in_path = name in full_path
        color = "#FFFFFF" if is_in_path else "#E0FFFF"
        
        canvas.create_oval(cx-WAFER_R, cy-WAFER_R, cx+WAFER_R, cy+WAFER_R, fill=color, outline="#888888")

        show_name = True 
        if is_in_path and wafer_img_mgr["original"]:
            rotated = wafer_img_mgr["original"].rotate(-display_angle)
            tk_img = ImageTk.PhotoImage(rotated)
            wafer_img_mgr["tk_refs"][name] = tk_img
            canvas.create_image(cx, cy, image=tk_img)
            show_name = False 

        notch_len = 6
        rad = math.radians(90 + display_angle)
        edge_x, edge_y = cx + WAFER_R * math.cos(rad), cy + WAFER_R * math.sin(rad)
        p1_x, p1_y = cx + (WAFER_R - notch_len) * math.cos(rad), cy + (WAFER_R - notch_len) * math.sin(rad)
        dx, dy = math.cos(rad), math.sin(rad)
        width_offset = 4 
        p2_x, p2_y = edge_x + width_offset * dy, edge_y - width_offset * dx
        p3_x, p3_y = edge_x - width_offset * dy, edge_y + width_offset * dx
        canvas.create_polygon(p1_x, p1_y, p2_x, p2_y, p3_x, p3_y, fill="red", outline="red")

        if show_name:
            canvas.create_text(cx, cy, text=name, fill="black", font=("Arial", 9, "bold"))
        
        if is_in_path:
            canvas.create_oval(cx-WAFER_R-4, cy-WAFER_R-4, cx+WAFER_R+4, cy+WAFER_R+4, outline="red", width=3)
            canvas.create_text(cx, cy-WAFER_R-15, text=f"{angle}°", fill="red", font=("Arial", 10, "bold"))

# ----------------- 4. UI 邏輯 -----------------
def refresh_ui(info_text, canvas, c_var, st_var, prefix=""):
    info_text.config(state="normal")
    info_text.delete("1.0", tk.END)
    sel_c, sel_st = c_var.get(), st_var.get()
    path = get_full_path(sel_c, current_side, sel_st)
    msg = f"{prefix}\n[進站角度]: {base_angle}° | [路徑]: " + " -> ".join([f"{n}({get_node_angle(n, sel_c, current_side, base_angle)}°)" for n in path])
    info_text.insert(tk.END, msg)
    info_text.config(state="disabled")
    draw_layout(canvas, sel_st, sel_c)

def set_base_angle(c_var, a_var, st_var, info, cvs):
    global base_angle
    try:
        base_angle = int(a_var.get())
        refresh_ui(info, cvs, c_var, st_var, "✅ 角度同步成功")
    except: messagebox.showerror("錯誤", "請輸入整數")

def upload_map(info, canvas, c_var, st_var):
    f = filedialog.askopenfilename(filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp")])
    if f:
        img = Image.open(f).convert("RGBA").resize((WAFER_R*2, WAFER_R*2), Image.LANCZOS)
        wafer_img_mgr["original"] = img
        refresh_ui(info, canvas, c_var, st_var, "✅ Map 已上傳")

# ----------------- 5. 主程式 -----------------
def main():
    root = tk.Tk()
    root.title("Wafer Visualizer v5.2")
    root.geometry("640x920")
    
    # --- 單行控制列 ---
    ctrl = tk.Frame(root, pady=10, padx=10)
    ctrl.pack(fill=tk.X)
    
    # CASS
    tk.Label(ctrl, text="CASS:").pack(side=tk.LEFT, padx=(0,2))
    c_var = tk.StringVar(value="A")
    ttk.Combobox(ctrl, textvariable=c_var, values=["A","B","C","D"], width=3, state="readonly").pack(side=tk.LEFT, padx=5)
    
    # SIDE
    tk.Label(ctrl, text="SIDE:").pack(side=tk.LEFT, padx=(5,2))
    s_var = tk.StringVar(value="S1")
    ttk.Combobox(ctrl, textvariable=s_var, values=["S1","S2"], width=4, state="readonly").pack(side=tk.LEFT, padx=5)
    
    # STATION
    tk.Label(ctrl, text="ST:").pack(side=tk.LEFT, padx=(5,2))
    st_var = tk.StringVar(value="LL")
    ttk.Combobox(ctrl, textvariable=st_var, values=["LL","CHA","CHB","CHC"], width=6, state="readonly").pack(side=tk.LEFT, padx=5)
    
    # 角度
    tk.Label(ctrl, text="角度:").pack(side=tk.LEFT, padx=(5,2))
    a_var = tk.StringVar(value="0")
    tk.Entry(ctrl, textvariable=a_var, width=5).pack(side=tk.LEFT, padx=5)
    
    # 按鈕群
    tk.Button(ctrl, text="更新", command=lambda: set_base_angle(c_var, a_var, st_var, info_text, cvs), bg="#E8F5E9").pack(side=tk.LEFT, padx=5)
    tk.Button(ctrl, text="上傳 MAP", command=lambda: upload_map(info_text, cvs, c_var, st_var), bg="#E1F5FE").pack(side=tk.LEFT, padx=5)
    
    # --- 畫布與資訊欄 ---
    cvs = tk.Canvas(root, width=CANVAS_WIDTH, height=CANVAS_HEIGHT, bg="white", highlightthickness=0)
    cvs.pack(pady=5)
    
    info_text = tk.Text(root, height=5, bg="#F8F8F8", font=("Microsoft JhengHei", 10))
    info_text.pack(fill=tk.X, padx=10, pady=5)
    
    def on_change(*args):
        global current_side
        current_side = s_var.get()
        refresh_ui(info_text, cvs, c_var, st_var)
    
    c_var.trace_add("write", on_change)
    s_var.trace_add("write", on_change)
    st_var.trace_add("write", on_change)
    
    refresh_ui(info_text, cvs, c_var, st_var)
    root.mainloop()

if __name__ == "__main__": main()