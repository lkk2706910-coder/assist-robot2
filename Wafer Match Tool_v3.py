import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import math
from PIL import Image, ImageTk, ImageGrab, ImageDraw, ImageOps

# ----------------- 1. 全域配置與設備座標 -----------------
REF_W, REF_H = 600, 750
REF_WAFER_R = 45

def to_ratio(pos_dict): return {k: (v[0]/REF_W, v[1]/REF_H) for k, v in pos_dict.items()}
def to_ratio_box(box_dict): return {k: (v[0]/REF_W, v[1]/REF_H, v[2]/REF_W, v[3]/REF_H) for k, v in box_dict.items()}

RAW_WAFER_POS = {
    "A2": (245, 55), "A1": (355, 55), "B1": (135, 165), "B2": (135, 275),
    "C2": (465, 165), "C1": (465, 275), "LL1": (200, 385), "LL2": (400, 385),
    "CS": (300, 515), "CA": (150, 670), "CB": (250, 670), "CC": (350, 670), "CD": (450, 670),
}
RAW_MODULE_BOXES = {
    "CHA": (190, 0, 410, 110), "CHB": (80, 110, 190, 330), "CHC": (410, 110, 520, 330),
    "MF": (190, 110, 410, 330), "LL": (80, 330, 520, 440), "Cooling": (250, 440, 350, 590),
    "CassA": (100, 590, 200, 720), "CassB": (200, 590, 300, 720), "CassC": (300, 590, 400, 720), "CassD": (400, 590, 500, 720),
}
RAW_LABEL_POS = {
    "CHA": (300, 20), "CHB": (135, 220), "CHC": (465, 220), "MF": (300, 220),
    "LL": (300, 350), "Cooling": (300, 460), "CassA": (150, 600), "CassB": (250, 600), "CassC": (350, 600), "CassD": (450, 600),
}

RATIO_WAFER_POS = to_ratio(RAW_WAFER_POS)
RATIO_MODULE_BOXES = to_ratio_box(RAW_MODULE_BOXES)
RATIO_LABEL_POS = to_ratio(RAW_LABEL_POS)

# ----------------- 2. 狀態管理 -----------------
wafer_img_mgr = {"original": None, "tk_refs": {}}
popup_img_refs = {}
base_angle = 0

# ----------------- 3. 核心功能：精確對中裁切 -----------------
def get_circular_wafer(img, size):
    img = img.convert("RGBA")
    w, h = img.size
    crop_factor = 0.92
    min_dim = min(w, h)
    crop_size = min_dim * crop_factor
    left = (w - crop_size) / 2
    top = (h - crop_size) / 2
    img_square = img.crop((left, top, left + crop_size, top + crop_size))
    img_resized = img_square.resize((size, size), Image.Resampling.LANCZOS)
    
    mask = Image.new('L', (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((1, 1, size-1, size-1), fill=255)
    output = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    output.paste(img_resized, (0, 0))
    output.putalpha(mask)
    draw_edge = ImageDraw.Draw(output)
    draw_edge.ellipse((0, 0, size-1, size-1), outline="black", width=1)
    return output

# ----------------- 4. 角度與路徑邏輯 -----------------
def get_node_angle(mode, node_name, cass_name, side, start_angle):
    if node_name in ["CA", "CB", "CC", "CD"]: return (start_angle) % 360
    rules = {}
    if mode == "FI5.X":
        if cass_name in ("A", "B"):
            rules = {"LL1": 210, "A1": 30, "B1": 300, "C1": 120, "CS": 0} if side == "S1" else {"CS": 300, "LL2": 0, "A2": 180, "B2": 90, "C2": 270}
        else:
            rules = {"CS": 30, "LL1": 0, "A1": 180, "B1": 90, "C1": 270} if side == "S1" else {"LL2": 150, "A2": 330, "B2": 240, "C2": 60, "CS": 0}
    else: # FI6.4
        if cass_name in ("A", "B"):
            rules = {"LL1": 195, "A1": 15, "B1": 285, "C1": 105, "CS": 0} if side == "S1" else {"CS": 255, "LL2": 345, "A2": 165, "B2": 75, "C2": 255}
        else:
            rules = {"CS": 105, "LL1": 15, "A1": 195, "B1": 105, "C1": 285} if side == "S1" else {"LL2": 165, "A2": 345, "B2": 255, "C2": 75, "CS": 0}
    return (rules.get(node_name, 0) + start_angle) % 360

def get_full_path(cass_name, side, station):
    path = [f"C{cass_name}"]
    if (cass_name in ("A", "B") and side == "S2") or (cass_name in ("C", "D") and side == "S1"):
        path.append("CS")
    path.append("LL1" if side == "S1" else "LL2")
    if station != "LL":
        target = {"CHA":"A", "CHB":"B", "CHC":"C"}[station]
        path.append(f"{target}{'1' if side == 'S1' else '2'}")
    return path

# ----------------- 5. 彈出視窗 (修正 Slit Valve 往 MF 方向) -----------------
def show_popup(node_name, angle):
    if not wafer_img_mgr["original"]: return
    pop = tk.Toplevel(); pop.title(f"Zoom View: {node_name}")
    canvas_size, wafer_size = 550, 550
    display_angle = (180 + angle) % 360
    p_cvs = tk.Canvas(pop, width=canvas_size, height=canvas_size, bg="white", highlightthickness=0); p_cvs.pack()
    
    circ_img = get_circular_wafer(wafer_img_mgr["original"], 420)
    tk_img = ImageTk.PhotoImage(circ_img.rotate(-display_angle, resample=Image.Resampling.BICUBIC))
    popup_img_refs[node_name] = tk_img 
    
    cx, cy = canvas_size/2, canvas_size/2
    p_cvs.create_image(cx, cy, image=tk_img)

    # 根據 Layout 決定 Slit Valve 位置 (指向 MF 方向)
    # CHA 在上 -> SV 在下 | CHB 在左 -> SV 在右 | CHC 在右 -> SV 在左 | LL 在下 -> SV 在上
    sv_config = {
        "A": {"pos": (cx, cy + 250), "rot": 0},    # CHA 往南
        "B": {"pos": (cx + 250, cy), "rot": 90},   # CHB 往東
        "C": {"pos": (cx - 250, cy), "rot": 90},   # CHC 往西
        "LL": {"pos": (cx, cy - 250), "rot": 0}    # LL 往北
    }

    target_key = next((k for k in sv_config if k in node_name), None)
    
    if target_key:
        cfg = sv_config[target_key]
        v_w, v_h = (360, 25) if cfg["rot"] == 0 else (25, 360)
        vx, vy = cfg["pos"]
        p_cvs.create_rectangle(vx-v_w/2, vy-v_h/2, vx+v_w/2, vy+v_h/2, fill="#3B9CFF", outline="")
        
        # 文字旋轉處理
        txt_angle = cfg["rot"]
        p_cvs.create_text(vx, vy, text="SLIT VALVE", fill="white", font=("Arial", 11, "bold"), angle=txt_angle)
    
    p_cvs.create_text(cx, canvas_size-15, text=f"Station: {node_name} | Rotation: {angle}°", font=("Arial", 10, "bold"))

# ----------------- 6. 核心繪圖邏輯 -----------------
def draw_layout(canvas, m_var, c_var, s_var, st_var):
    canvas.delete("all")
    W, H = canvas.winfo_width(), canvas.winfo_height()
    if W < 10: return
    scale = min(W/REF_W, H/REF_H)
    cur_r = REF_WAFER_R * scale
    
    for name, (rx1, ry1, rx2, ry2) in RATIO_MODULE_BOXES.items():
        canvas.create_rectangle(rx1*W, ry1*H, rx2*W, ry2*H, outline="#0015D1", width=2)
        tx, ty = RATIO_LABEL_POS.get(name, ((rx1+rx2)/2, ry1))
        canvas.create_text(tx*W, ty*H, text=name, fill="#5C6BC0", font=("Arial", int(9*scale), "bold"))

    mode, sel_c, sel_s, sel_st = m_var.get(), c_var.get(), s_var.get(), st_var.get()
    full_path = get_full_path(sel_c, sel_s, sel_st)
    wafer_img_mgr["tk_refs"] = {}

    for name, (rx, ry) in RATIO_WAFER_POS.items():
        cx, cy = rx * W, ry * H
        angle = get_node_angle(mode, name, sel_c, sel_s, base_angle)
        display_angle = (180 + angle) % 360
        is_in_path, tag = name in full_path, f"w_{name}"
        canvas.create_oval(cx-cur_r, cy-cur_r, cx+cur_r, cy+cur_r, fill="#FFFFFF" if is_in_path else "#E0FFFF", outline="#888888", tags=(tag, "clickable"))
        
        if is_in_path and wafer_img_mgr["original"]:
            img_size = int(cur_r * 2)
            circ_img = get_circular_wafer(wafer_img_mgr["original"], img_size)
            tk_img = ImageTk.PhotoImage(circ_img.rotate(-display_angle, resample=Image.Resampling.BICUBIC))
            wafer_img_mgr["tk_refs"][name] = tk_img
            canvas.create_image(cx, cy, image=tk_img, tags=(tag, "clickable"))
        else:
            canvas.create_text(cx, cy, text=name, fill="#BBBBBB" if not is_in_path else "black", font=("Arial", int(9*scale)), tags=(tag, "clickable"))
        
        rad = math.radians(90 + display_angle)
        n_len, w_off = 9 * scale, 4 * scale
        ex, ey = cx + cur_r * math.cos(rad), cy + cur_r * math.sin(rad)
        p1x, p1y = cx + (cur_r - n_len) * math.cos(rad), cy + (cur_r - n_len) * math.sin(rad)
        canvas.create_polygon(p1x, p1y, ex + w_off * math.sin(rad), ey - w_off * math.cos(rad), 
                               ex - w_off * math.sin(rad), ey + w_off * math.cos(rad), fill="#F44336", tags=(tag, "clickable"))
        if is_in_path:
            canvas.create_oval(cx-cur_r-2, cy-cur_r-2, cx+cur_r+2, cy+cur_r+2, outline="#FF5252", width=2, tags=(tag, "clickable"))
            canvas.create_text(cx, cy-cur_r-15*scale, text=f"{angle}°", fill="#D32F2F", font=("Arial", int(10*scale), "bold"))
        canvas.tag_bind(tag, "<Button-1>", lambda e, n=name, a=angle: show_popup(n, a))


# ----------------- 7. 主程式介面 -----------------
def main():
    root = tk.Tk(); root.title("Wafer Match Tool v3整合版"); root.geometry("640x940")
    ctrl = tk.Frame(root, pady=10, padx=10); ctrl.pack(fill=tk.X)
    m_var, c_var, s_var, st_var, a_var = [tk.StringVar(value=v) for v in ["FI5.X", "A", "S1", "LL", "0"]]
    
    ttk.Combobox(ctrl, textvariable=m_var, values=["FI5.X", "FI6.4"], width=7, state="readonly").pack(side=tk.LEFT, padx=5)
    for lab, v, vals, w in [("CASS:", c_var, ["A","B","C","D"], 3), ("SIDE:", s_var, ["S1","S2"], 4), ("目標:", st_var, ["LL","CHA","CHB","CHC"], 6)]:
        tk.Label(ctrl, text=lab).pack(side=tk.LEFT)
        ttk.Combobox(ctrl, textvariable=v, values=vals, width=w, state="readonly").pack(side=tk.LEFT, padx=5)
    
    tk.Label(ctrl, text="Offset:").pack(side=tk.LEFT)
    tk.Entry(ctrl, textvariable=a_var, width=4).pack(side=tk.LEFT, padx=5)
    
    def on_refresh(*args):
        global base_angle
        val = a_var.get()
        if val == "" or val == "-": base_angle = 0
        else:
            try: base_angle = int(val)
            except: base_angle = 0
        draw_layout(cvs, m_var, c_var, s_var, st_var)

    tk.Button(ctrl, text="上傳圖片", command=lambda: handle_upload(), bg="#E3F2FD", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=5)
    cvs = tk.Canvas(root, bg="white", highlightthickness=0); cvs.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
    

    def handle_upload():
        f = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp")])
        if f:
            wafer_img_mgr["original"] = Image.open(f)
            on_refresh()

    def handle_paste(event):
        img = ImageGrab.grabclipboard()
        if isinstance(img, Image.Image):
            wafer_img_mgr["original"] = img
            on_refresh()

    root.bind("<Control-v>", handle_paste); root.bind("<Control-V>", handle_paste)
    cvs.bind("<Configure>", lambda e: on_refresh())
    for v in [m_var, c_var, s_var, st_var, a_var]: v.trace_add("write", on_refresh)
    root.after(100, on_refresh); root.mainloop()

if __name__ == "__main__": main()