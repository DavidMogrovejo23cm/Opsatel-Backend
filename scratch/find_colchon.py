import pandas as pd

def find_colchon():
    path = r'c:\Users\Dagumo\GITHUB\Opsatel-Backend\2026 ADMNISTRACION(1).xlsx'
    xl = pd.ExcelFile(path)
    for sheet in xl.sheet_names:
        df = xl.parse(sheet, header=None)
        for r in range(df.shape[0]):
            for c in range(df.shape[1]):
                val = str(df.iloc[r, c]).upper()
                if 'COLCHON' in val:
                    print(f"Sheet: {sheet} | Row: {r} | Col: {c} | Val: {df.iloc[r, c]}")
                    if c + 1 < df.shape[1]:
                        print(f"  Next Val: {df.iloc[r, c+1]}")
                    if r + 1 < df.shape[0]:
                        print(f"  Below Val: {df.iloc[r+1, c]}")

find_colchon()
