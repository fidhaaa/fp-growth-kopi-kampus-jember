import pandas as pd
import os
from mlxtend.preprocessing import TransactionEncoder
from mlxtend.frequent_patterns import fpgrowth, association_rules

DEFAULT_MIN_SUPPORT = 0.005
DEFAULT_MIN_CONFIDENCE = 0.30

MENU_FILE = os.path.join(
    os.path.dirname(__file__),
    "..",
    "data",
    "produk_valid.xlsx"
)

def load_menu_mapping():
    menu_df = pd.read_excel(MENU_FILE)

    original = menu_df.iloc[:, 0].astype(str).str.strip()
    lower = original.str.lower()

    return dict(zip(lower, original))

# FP-Growth analysis function
def analyze_fp_growth_from_list(transactions, min_support=DEFAULT_MIN_SUPPORT, min_confidence=DEFAULT_MIN_CONFIDENCE):
    menu_mapping = load_menu_mapping()
    try:
        if not transactions or not any(transactions):
            return None, 'Data transaksi kosong atau tidak sesuai format.'

        te = TransactionEncoder()
        te_ary = te.fit(transactions).transform(transactions)
        df = pd.DataFrame(te_ary, columns=te.columns_)

        if df.empty:
            return None, 'Data transaksi kosong setelah encoding.'

        freq_items = fpgrowth(df, min_support=min_support, use_colnames=True)
        print("Frequent itemsets:", len(freq_items))
        print(freq_items.head(10))
        if freq_items.empty:
            return None, 'Tidak ditemukan frequent itemsets.'

        rules = association_rules(freq_items, num_itemsets=len(df),metric="confidence", min_threshold=min_confidence)
        print("Jumlah rules sebelum filter:", len(rules))
        if rules.empty:
            return None, 'Tidak ditemukan aturan asosiasi.'
        
        rules = rules[rules["lift"] > 1]

        rules = rules.sort_values(
            by="lift",
            ascending=False
        ).reset_index(drop=True)

        results = []
        for _, row in rules.iterrows():
            # results.append({
            #     "antecedents": list(row['antecedents']),
            #     "consequents": list(row['consequents']),
            #     "confidence": float(row['confidence']),
            #     "lift": float(row['lift'])
            # })
            results.append({
                "antecedents": [
                    menu_mapping.get(item, item)
                    for item in row["antecedents"]
                ],
                "consequents": [
                    menu_mapping.get(item, item)
                    for item in row["consequents"]
                ],
                "confidence": float(row["confidence"]),
                "lift": float(row["lift"])
            })

        return results, None  # results = list of dict
    except Exception as e:
        return None, f"Gagal menganalisis data: {str(e)}"
