"""繁體中文譯文的存放與查找（風險因素年度變化用）。

年度比對的新增／刪除段落是 SEC 申報書的**原文**，全部是英文。報告頁其餘部分
都是中文，讀者要看懂這一節得自己讀法律英文，等於這節實際上沒被讀。

譯文不能由管線推導，也不能即時產生（本庫不呼叫外部翻譯服務），因此存成一份
對照檔：`risk_zh.json`。設計上有三個約束：

1. **原文永遠保留**。譯文顯示在前，原文完整收在頁面的 `<details>` 裡。翻譯是
   人的轉述，不是資料；把原文換掉就等於讓報告失去可查證性。
2. **以原文的雜湊為鍵**。申報書改一個字，鍵就變了，舊譯文自動失效並回到
   「尚未翻譯」，而不是安靜地掛在一段已經不同的原文上。
3. **缺譯文不是錯誤**。新申報書一定會帶來沒翻過的段落，那時頁面顯示原文並
   標示「尚未翻譯」，不會空白，也不會假裝翻過。

    python3 scripts/list_untranslated.py     # 列出待翻譯的段落
"""

import hashlib
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STORE_PATH = REPO_ROOT / "risk_zh.json"

# 頁面上每段只顯示開頭。切在句子邊界而不是固定字元數，是因為譯文要通順，
# 而「…we may have to curtail」這種半句話翻出來只會更難讀。
EXCERPT_CHARS = 320


# 版面殘留：頁首（"Apple Inc. | 2025 Form 10-K | 7 "）與被 reflow 併進句子的頁碼
# （"...and launch 11."）。這些在原文拆解裡本來就在，比對時無害，但翻譯出來會
# 變成不知所云的句子，所以只在顯示用的摘錄裡清掉。
RUNNING_HEADER = re.compile(r"^.{0,40}?Form 10-K \| \d+ ", re.I)
TRAILING_PAGE_NUMBER = re.compile(r"\s+\d{1,3}\.?$")


def tidy(text):
    text = " ".join(text.split())
    text = RUNNING_HEADER.sub("", text)
    return TRAILING_PAGE_NUMBER.sub("", text)


def excerpt(paragraph):
    """段落開頭，切在句號上，長度以 EXCERPT_CHARS 為上限。"""
    text = tidy(paragraph)
    if len(text) <= EXCERPT_CHARS:
        return text
    window = text[:EXCERPT_CHARS]
    # 句點後接空白才算句子結束，避免切在 "U.S." 或 "Inc." 上。
    ends = [m.end() for m in re.finditer(r"[.?!](?=\s)", window)]
    if ends and ends[-1] > EXCERPT_CHARS * 0.4:
        return tidy(window[:ends[-1]])
    return tidy(window.rsplit(" ", 1)[0]) + "…"


def key(text):
    """譯文的鍵：摘錄原文的雜湊。原文一改，鍵就不同，舊譯文自動失效。"""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def load():
    if not STORE_PATH.exists():
        return {}
    return json.loads(STORE_PATH.read_text()).get("translations", {})


def lookup(store, paragraph):
    """(摘錄原文, 譯文或 None)。"""
    piece = excerpt(paragraph)
    entry = store.get(key(piece))
    return piece, (entry or {}).get("zh")
