import pandas as pd
import json
import os

def export_xlsx_to_json():
    db = {}
    files = [f for f in os.listdir('.') if f.endswith('.xlsx')]
    
    for file in files:
        print(f"正在處理: {file}")
        xl = pd.ExcelFile(file)
        for sheet in xl.sheet_names:
            try:
                df = pd.read_excel(file, sheet_name=sheet, header=None)
                # 依照您的規範：
                # A2 (index 1,0) = Entity
                # B2 (index 1,1) = Recipe
                entity = str(df.iloc[1, 0]).strip()
                recipe = str(df.iloc[1, 1]).strip()
                
                # A4:B 開始是數據 (index 3 開始)
                coords = df.iloc[3:].dropna(subset=[0, 1])
                x_list = coords[0].astype(float).tolist()
                y_list = coords[1].astype(float).tolist()
                
                if entity not in db: db[entity] = {}
                db[entity][recipe] = {"X": x_list, "Y": y_list}
            except Exception as e:
                print(f"工作表 {sheet} 格式不符跳過: {e}")

    with open('wafer_configs.json', 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=4, ensure_ascii=False)
    print("轉換完成！已生成 wafer_configs.json")

if __name__ == "__main__":
    export_xlsx_to_json()