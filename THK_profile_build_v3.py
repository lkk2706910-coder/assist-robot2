import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patheffects as path_effects
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from scipy.interpolate import griddata
from scipy.spatial import KDTree
import tkinter as tk
from tkinter import ttk, messagebox
import re
import os
import sys
import json

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

class WaferApp:
    def __init__(self, root):
        self.root = root
        self.root.title("THK Profile Generator v3")
        self.root.geometry("1200x800")

        self.json_path = resource_path('wafer_configs.json')
        self.db = {} # 格式: {Entity: {Recipe: {'X': [], 'Y': []}}}
        self.data_slots = ["A", "B", "C", "D", "E"]
        self.current_slot = "A"
        self.selected_slot_idx = None
        self.input_widgets = []
        self.storage = {}

        self.load_initial_data()
        self.setup_ui()
        
        if self.db:
            self.update_recipe_list()

    def load_initial_data(self):
        """讀取 JSON 檔案"""
        if os.path.exists(self.json_path):
            try:
                with open(self.json_path, 'r', encoding='utf-8') as f:
                    self.db = json.load(f)
                if not self.db: raise ValueError("JSON 檔案內無資料")
            except Exception as e:
                messagebox.showerror("載入失敗", f"JSON 錯誤: {e}")
                self.use_demo_data()
        else:
            self.use_demo_data()

    def use_demo_data(self):
        self.db = {"Demo_Entity": {"Demo_Recipe": {
            'X': [0, 50, -50, 0, 0], 
            'Y': [0, 0, 0, 50, -50]
        }}}

    def setup_ui(self):
        left_frame = ttk.Frame(self.root, padding="10")
        left_frame.pack(side=tk.LEFT, fill=tk.Y)

        # 1. 雙層選擇區
        select_frame = ttk.LabelFrame(left_frame, text="1. Entity&Recipe設定", padding="5")
        select_frame.pack(fill=tk.X, pady=5)

        ttk.Label(select_frame, text="Entity:", font=('Arial', 9, 'bold')).pack(anchor=tk.W)
        self.ent_combo = ttk.Combobox(select_frame, values=list(self.db.keys()), state="readonly")
        self.ent_combo.pack(fill=tk.X, pady=(2, 8))
        self.ent_combo.bind("<<ComboboxSelected>>", self.update_recipe_list)
        if self.db: self.ent_combo.current(0)

        ttk.Label(select_frame, text="Recipe:", font=('Arial', 9, 'bold')).pack(anchor=tk.W)
        self.rec_combo = ttk.Combobox(select_frame, state="readonly")
        self.rec_combo.pack(fill=tk.X, pady=(2, 5))
        self.rec_combo.bind("<<ComboboxSelected>>", self.on_config_change)

        # 2. 組別切換
        ttk.Label(left_frame, text="當前輸入組別:", font=('Arial', 9, 'bold')).pack(anchor=tk.W, pady=(10,0))
        slot_frame = ttk.Frame(left_frame)
        slot_frame.pack(fill=tk.X, pady=5)
        self.slot_var = tk.StringVar(value="A")
        for slot in self.data_slots:
            rb = tk.Radiobutton(slot_frame, text=slot, variable=self.slot_var, value=slot, indicatoron=0, width=4, command=self.switch_slot)
            rb.pack(side=tk.LEFT, padx=1)

        # 3. 資料貼入
        paste_frame = ttk.LabelFrame(left_frame, text="2. RAW DATA 貼入", padding="5")
        paste_frame.pack(fill=tk.X, pady=5)
        self.paste_area = tk.Text(paste_frame, height=3, width=30, font=('Arial', 9))
        self.paste_area.pack(pady=5)
        ttk.Button(paste_frame, text="⚡ 自動擷取並分派", command=self.distribute_data).pack(fill=tk.X)

        # 4. 點位輸入列表
        ttk.Label(left_frame, text="3. 點位數值編輯:", font=('Arial', 9, 'bold')).pack(anchor=tk.W, pady=(10, 2))
        canvas_container = ttk.Frame(left_frame)
        canvas_container.pack(fill=tk.BOTH, expand=True)
        
        self.canvas_scroll = tk.Canvas(canvas_container, width=230, height=300)
        self.scrollbar = ttk.Scrollbar(canvas_container, orient="vertical", command=self.canvas_scroll.yview)
        self.scrollable_frame = ttk.Frame(self.canvas_scroll)
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas_scroll.configure(scrollregion=self.canvas_scroll.bbox("all")))
        self.canvas_scroll.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas_scroll.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas_scroll.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        tk.Button(left_frame, text="繪製當前組 Profile", bg="#007bff", fg="white", font=('Arial', 10, 'bold'), command=self.draw_plot).pack(fill=tk.X, pady=5)
        tk.Button(left_frame, text="📊 5 組全覽對比", bg="#28a745", fg="white", font=('Arial', 10, 'bold'), command=self.compare_all).pack(fill=tk.X, pady=5)

        self.plot_frame = ttk.Frame(self.root, padding="5")
        self.plot_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

    def update_recipe_list(self, event=None):
        ent = self.ent_combo.get()
        if ent in self.db:
            recipes = list(self.db[ent].keys())
            self.rec_combo['values'] = recipes
            self.rec_combo.current(0)
            self.on_config_change()

    def on_config_change(self, event=None):
        ent, rec = self.ent_combo.get(), self.rec_combo.get()
        if ent and rec:
            point_count = len(self.db[ent][rec]['X'])
            self.storage = {slot: [""] * point_count for slot in self.data_slots}
            self.refresh_inputs()

    def switch_slot(self):
        self.storage[self.current_slot] = [e.get() for e in self.input_widgets]
        self.current_slot = self.slot_var.get()
        self.refresh_inputs()

    def refresh_inputs(self):
        for widget in self.scrollable_frame.winfo_children(): widget.destroy()
        self.input_widgets = []
        ent, rec = self.ent_combo.get(), self.rec_combo.get()
        model = self.db[ent][rec]
        saved_vals = self.storage[self.current_slot]
        for i in range(len(model['X'])):
            f = ttk.Frame(self.scrollable_frame); f.pack(fill=tk.X, pady=1)
            ttk.Label(f, text=f"P{i+1}:", font=('Arial', 8)).pack(side=tk.LEFT)
            ent_val = ttk.Entry(f, width=12); ent_val.insert(0, saved_vals[i] if i < len(saved_vals) else "")
            ent_val.pack(side=tk.RIGHT); self.input_widgets.append(ent_val)

    def distribute_data(self):
        raw_text = self.paste_area.get("1.0", tk.END).strip()
        all_numbers = re.findall(r"[-+]?\d*\.\d+|\d+", raw_text)
        if not all_numbers: return
        target_count = len(self.input_widgets)
        selected = all_numbers[-target_count:] if len(all_numbers) >= target_count else all_numbers
        for i, val in enumerate(selected):
            if i < target_count:
                self.input_widgets[i].delete(0, tk.END); self.input_widgets[i].insert(0, val)
        self.storage[self.current_slot] = [e.get() for e in self.input_widgets]
        self.paste_area.delete("1.0", tk.END)

    def embed_plot(self, slot_key, parent_frame, is_popup=False):
        ent, rec = self.ent_combo.get(), self.rec_combo.get()
        if not ent or not rec: return
        model = self.db[ent][rec]
        vals_str = self.storage[slot_key]
        try:
            thk = np.array([float(val) for val in vals_str if val.strip()], dtype=float)
            if len(thk) < len(model['X']): return
        except: return

        avg, std = thk.mean(), thk.std(ddof=1)
        v_max, v_min = thk.max(), thk.min()
        rng = v_max - v_min
        u_pct = (rng / (2 * avg)) * 100 if avg != 0 else 0

        R = 150
        grid_x, grid_y = np.mgrid[-R:R:300j, -R:R:300j]
        theta = np.linspace(0, 2*np.pi, 100)
        edge_x, edge_y = R * np.cos(theta), R * np.sin(theta)
        tree = KDTree(np.column_stack((model['X'], model['Y'])))
        _, idx = tree.query(np.column_stack((edge_x, edge_y)))
        all_x, all_y = np.concatenate([model['X'], edge_x]), np.concatenate([model['Y'], edge_y])
        all_v = np.concatenate([thk, thk[idx]])
        grid_z = griddata((all_x, all_y), all_v, (grid_x, grid_y), method='cubic')
        grid_z[grid_x**2 + grid_y**2 > R**2] = np.nan

        fig = plt.figure(figsize=(7, 8) if is_popup else (6, 7), dpi=95)
        ax = fig.add_axes([0.05, 0.22, 0.85, 0.75])
        ax.set_aspect('equal', adjustable='box') 
        ax.set_xlim(-R-10, R+10); ax.set_ylim(-R-10, R+10); ax.set_axis_off()

        cp = ax.contourf(grid_x, grid_y, grid_z, levels=50, cmap='jet')
        plt.colorbar(cp, fraction=0.046, pad=0.04).set_label('Å')
        ax.add_artist(plt.Circle((0, 0), R, color='black', fill=False, lw=1.5))
        
        for i in range(len(thk)):
            x, y = model['X'][i], model['Y'][i]
            dist = np.sqrt(x**2 + y**2)
            dx, dy = (x * 0.92, y * 0.92) if dist > R * 0.85 else (x, y + 2.5)
            ax.text(dx, dy, f"{thk[i]:.1f}", fontsize=9 if is_popup else 7, ha='center', va='center', weight='bold',
                    path_effects=[path_effects.withStroke(linewidth=2, foreground='white')])
        
        stat_text = f"Avg:  {avg:3.1f}\n1Sig: {std:1.1f} ({std/avg*100:.1f}%)\nRng:  {rng:2.1f}\nU%:   {u_pct:1.2f}"
        fig.text(0.1, 0.05, stat_text, fontsize=12, fontfamily='monospace', fontweight='bold')
        ax.set_title(f"Slot {slot_key} Detail", fontsize=14, fontweight='bold')
        canvas = FigureCanvasTkAgg(fig, master=parent_frame); canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True); plt.close(fig)

    def draw_plot(self):
        self.storage[self.current_slot] = [e.get() for e in self.input_widgets]
        for widget in self.plot_frame.winfo_children(): widget.destroy()
        self.embed_plot(self.current_slot, self.plot_frame)

    def compare_all(self):
        self.storage[self.current_slot] = [e.get() for e in self.input_widgets]
        ent, rec = self.ent_combo.get(), self.rec_combo.get()
        if not ent or not rec: return
            
        self.compare_win = tk.Toplevel(self.root); self.compare_win.title("Comparison View"); self.compare_win.geometry("1550x650")
        self.comp_fig, self.compare_axes = plt.subplots(1, 5, figsize=(15, 6))
        self.comp_fig.subplots_adjust(left=0.02, right=0.98, bottom=0.25, top=0.9, wspace=0.1)
        model, R = self.db[ent][rec], 150

        for i, slot in enumerate(self.data_slots):
            ax = self.compare_axes[i]
            ax.set_aspect('equal', adjustable='box')
            try:
                vals = np.array([float(x) for x in self.storage[slot] if x.strip()], dtype=float)
                if len(vals) < len(model['X']): raise ValueError
                avg, std, rng = vals.mean(), vals.std(ddof=1), vals.max() - vals.min()
                u_pct = (rng / (2 * avg)) * 100 if avg != 0 else 0
                
                grid_x, grid_y = np.mgrid[-R:R:150j, -R:R:150j]
                theta = np.linspace(0, 2*np.pi, 80); edge_x, edge_y = R * np.cos(theta), R * np.sin(theta)
                tree = KDTree(np.column_stack((model['X'], model['Y']))); _, idx = tree.query(np.column_stack((edge_x, edge_y)))
                ax.contourf(grid_x, grid_y, griddata((np.concatenate([model['X'], edge_x]), np.concatenate([model['Y'], edge_y])), 
                            np.concatenate([vals, vals[idx]]), (grid_x, grid_y), method='cubic'), levels=30, cmap='jet')
                ax.add_artist(plt.Circle((0, 0), R, color='black', fill=False, lw=1))
                
                for j in range(len(vals)):
                    px, py = model['X'][j], model['Y'][j]
                    dist = np.sqrt(px**2 + py**2)
                    dx, dy = (px * 0.88, py * 0.88) if dist > R * 0.85 else (px, py + 1.5)
                    ax.text(dx, dy, f"{vals[j]:.0f}", fontsize=6, ha='center', va='center', fontweight='bold',
                            path_effects=[path_effects.withStroke(linewidth=1.5, foreground='white')])

                ax.axis('off'); ax.set_title(f"Slot {slot}", fontsize=12, fontweight='bold')
                stat_str = f"Avg: {avg:.1f}\n1Sig: {std:.1f}\nRng: {rng:.1f}\nU%: {u_pct:.2f}"
                ax.text(0.5, -0.18, stat_str, transform=ax.transAxes, fontsize=9, ha='center', va='top', bbox=dict(boxstyle='round', facecolor='white', alpha=0.7))
            except: 
                ax.text(0.5, 0.5, f"Slot {slot}\nNo Data", ha='center', transform=ax.transAxes); ax.axis('off')

        self.comp_canvas = FigureCanvasTkAgg(self.comp_fig, master=self.compare_win); self.comp_canvas.draw()
        self.comp_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.comp_fig.canvas.mpl_connect('button_press_event', self.on_comp_click)
        self.compare_win.bind("<Control-c>", self.copy_selected_data)

    def on_comp_click(self, event):
        if event.inaxes:
            for idx, ax in enumerate(self.compare_axes):
                if event.inaxes == ax:
                    if self.selected_slot_idx == idx: self.show_zoom_window(self.data_slots[idx])
                    else: self.selected_slot_idx = idx; self.update_selection_highlight()
                    break

    def update_selection_highlight(self):
        for i, ax in enumerate(self.compare_axes):
            for patch in [p for p in ax.patches if getattr(p, 'is_selection_box', False)]: patch.remove()
            if i == self.selected_slot_idx:
                rect = plt.Rectangle((-155, -155), 310, 310, fill=False, edgecolor='red', linewidth=3, linestyle='--')
                rect.is_selection_box = True; ax.add_patch(rect)
        self.comp_canvas.draw()

    def copy_selected_data(self, event=None):
        if self.selected_slot_idx is None: return
        vals = self.storage[self.data_slots[self.selected_slot_idx]]
        if not any(v.strip() for v in vals): return
        self.root.clipboard_clear(); self.root.clipboard_append("\n".join([f"P{i+1}\t{v}" for i, v in enumerate(vals)]))
        messagebox.showinfo("Success", "Data copied.")

    def show_zoom_window(self, slot_key):
        zoom_win = tk.Toplevel(self.root); zoom_win.title(f"Slot {slot_key} Zoom View"); zoom_win.geometry("800x850")
        self.embed_plot(slot_key, zoom_win, is_popup=True)

if __name__ == "__main__":
    root = tk.Tk(); app = WaferApp(root); root.mainloop()