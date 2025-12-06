#!/usr/bin/env python3
# extract_dois_to_ris.py
# -*- coding: utf-8 -*-

import re
import sys
import time
import textwrap
from collections import OrderedDict
from pathlib import Path

import requests
from docx import Document
from tqdm import tqdm

# ------------ 设置：当前目录为目标 ------------
FOLDER = Path("/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/EphB1/08_manuscript")
OUT_RIS = FOLDER / "references_out.ris"
OUT_SKIP = FOLDER / "skipped_files.txt"
REGEX_DOI = re.compile(r"\{(10\.\d{4,9}/[^\}\s]+)\}", flags=re.IGNORECASE)

HEADERS = {
    "User-Agent": "doi-ris-extractor/0.2 (mailto:your_email@example.com)",
    "Accept": "application/x-research-info-systems",
}
# ---------------------------------------------

def extract_dois_from_doc(doc_path: Path, skipped_list: list[str]) -> list[str]:
    try:
        doc = Document(doc_path)
        full_text = "\n".join(p.text for p in doc.paragraphs)
        return REGEX_DOI.findall(full_text)
    except Exception as e:
        skipped_list.append(f"{doc_path.name} - {e}")
        return []

def fetch_ris(doi: str) -> str:
    url = f"https://api.crossref.org/works/{doi}/transform/application/x-research-info-systems"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 200 and "TY  -" in r.text:
            return r.text.strip()
    except Exception:
        pass
    return f"TY  - GEN\nDO  - {doi}\nER  -"

def main():
    docx_files = [FOLDER / "EphB1调控线粒体心磷脂含量减轻NLRP3炎症小体引发的焦亡.docx"]
    if not docx_files:
        print("❌ 当前目录没有找到 .docx 文件")
        sys.exit(1)

    all_dois = OrderedDict()
    skipped = []

    print(f"🔍 正在扫描 {len(docx_files)} 个 Word 文件 …")
    for docx in docx_files:
        for doi in extract_dois_from_doc(docx, skipped):
            all_dois[doi.lower()] = None  # 去重 + 保顺序

    if not all_dois:
        print("⚠ 没有发现任何 {DOI} 引用")
    else:
        print(f"🚀 开始抓取 Crossref，共 {len(all_dois)} 个唯一 DOI …")
        for doi in tqdm(all_dois, unit="DOI"):
            all_dois[doi] = fetch_ris(doi)
            time.sleep(0.1)  # 礼貌性等待

        OUT_RIS.write_text("\n\n".join(all_dois.values()), encoding="utf-8")
        print(f"✅ 已生成 RIS 文件：{OUT_RIS}")

    if skipped:
        OUT_SKIP.write_text("\n".join(skipped), encoding="utf-8")
        print(f"⚠ 以下文件无法解析，已写入：{OUT_SKIP}")
    else:
        print("✅ 所有 Word 文件均成功解析。")

if __name__ == "__main__":
    main()
