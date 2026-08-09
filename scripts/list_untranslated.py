"""列出報告頁會顯示、但 risk_zh.json 還沒有譯文的段落摘錄。

報告只顯示每家新增／刪除的前五段，所以待翻譯的範圍是那些，不是全部 413 段。
輸出可直接貼進 risk_zh.json 的 translations 區塊（zh 欄留空待填）。

    python3 scripts/list_untranslated.py            # 摘要
    python3 scripts/list_untranslated.py --json     # 待填的 JSON 骨架
"""

import argparse
import json
from pathlib import Path

from risk_translations import key, lookup, load

REPO_ROOT = Path(__file__).resolve().parent.parent
SHOWN_PER_SIDE = 5


def pending():
    data = json.loads((REPO_ROOT / "risk_changes.json").read_text())["companies"]
    store = load()
    out = {}
    for ticker, entry in sorted(data.items()):
        if entry.get("status") != "已比較":
            continue
        for side in ("added", "removed"):
            for para in entry[side][:SHOWN_PER_SIDE]:
                piece, zh = lookup(store, para)
                if zh is None:
                    out[key(piece)] = {"ticker": ticker, "side": side, "en": piece}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    todo = pending()
    if args.json:
        print(json.dumps({k: {"en": v["en"], "zh": ""} for k, v in todo.items()},
                         indent=1, ensure_ascii=False))
        return

    if not todo:
        print("待翻譯：無")
        return
    by_ticker = {}
    for k, v in todo.items():
        by_ticker.setdefault(v["ticker"], []).append(k)
    for ticker, keys in sorted(by_ticker.items()):
        print(f"{ticker:6s} {len(keys):3d} 段待翻譯")
    print(f"\n合計 {len(todo)} 段")


if __name__ == "__main__":
    main()
