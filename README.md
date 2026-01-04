# Google My Maps 用CSVの作り方（日本時価総額Top200 + 外資Tokyo 50）

## 1) 依存パッケージ
```bash
python -m pip install requests beautifulsoup4
```

## 2) 実行
```bash
python make_tokyo_company_maps.py
```

同一ディレクトリに以下が出力されます：
- `japan_top200_mymaps.csv`
- `foreign_tokyo50_mymaps.csv`

## 3) Google My Maps へのインポート
- Google My Maps を開く → 新しい地図 → 「インポート」
- CSV を選択
- 位置情報の列は `Address` を選択
- ラベル列は `Name` を選択

## 補足
- `Address` は “住所そのもの” ではなく、Google によるジオコーディングが効きやすい **検索クエリ形式** にしています（例: `会社名 本社 東京`）。
- もっと精度を上げたい場合は、列を `Tokyo office address` の公式表記に手直しするか、`Latitude/Longitude` を追加で持たせてください（Wikidata/Places API などで補完）。
