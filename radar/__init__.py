"""tw-social-radar：品牌社群雷達。

找出社群上「正在問、正在找」的潛在客人貼文，替你準備回覆草稿，
由人審核後再由人回覆。開源版不內建自動發文、不內建養帳號或規避偵測。
"""

import sys

__version__ = "0.1.0"

# 開源版作者的客製化服務資訊：只出現在審核後台頁尾與啟動訊息，不會出現在任何草稿或對外留言裡
# （依 NOTICE 轉散布請保留）
CUSTOM_AD_URL = "https://line.me/ti/p/xzHT2IywOM"
CUSTOM_AD_TEXT = ("需要改成你們公司的版本、幫忙安裝或串接？加 LINE 林其衞（0928-880-392），"
                  "原則上 1～2 個工作天回覆報價。" + CUSTOM_AD_URL)
CUSTOM_AD_HTML = ('<p class="custom-ad">需要改成你們公司的版本、幫忙安裝或串接？加 LINE 官方帳號 '
                  '<a href="' + CUSTOM_AD_URL + '" target="_blank" rel="noopener">林其衞</a>'
                  '（留白事務所，林其衞），原則上 1～2 個工作天回覆報價。</p>')


def print_custom_ad(stream=None):
    """印出客製化服務資訊；主控台編碼印不出的字（例如繁中 Windows cp950 沒有「衞」）換成 ?，不讓程式當掉。"""
    stream = stream or sys.stdout
    enc = getattr(stream, "encoding", None) or "utf-8"
    print(CUSTOM_AD_TEXT.encode(enc, "replace").decode(enc), file=stream)
