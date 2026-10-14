"""미국 상원 의원 주식 거래 신고(PTR) 수집 — GitHub Actions(미국 서버)에서 매일 돈다.

상원 공시 사이트(efdsearch.senate.gov)는 한국 서버 접속을 막아서, 미국에서 받아 이 저장소에 JSON 으로 둔다.
블로그 서버는 raw.githubusercontent.com 에서 data/senate_ptr.json 만 읽는다.

출력: data/senate_ptr.json — 최근 120일 신고서 목록과 거래 줄
"""
import json, re, html, time, datetime
from pathlib import Path
import requests

BASE = "https://efdsearch.senate.gov"
OUT = Path("data/senate_ptr.json")
CACHE = Path("data/reports"); CACHE.mkdir(parents=True, exist_ok=True)
DAYS = 120
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (research; github.com senate-ptr)"


def agree():
    r = S.get(BASE + "/search/home/", timeout=60); r.raise_for_status()
    tok = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', r.text).group(1)
    S.post(BASE + "/search/home/", data={"prohibition_agreement": "1", "csrfmiddlewaretoken": tok},
           headers={"Referer": BASE + "/search/home/"}, timeout=60).raise_for_status()


def search(since):
    out, start = [], 0
    while True:
        csrf = S.cookies.get("csrftoken")
        r = S.post(BASE + "/search/report/data/", headers={"Referer": BASE + "/search/", "X-CSRFToken": csrf}, timeout=60, data={
            "start": str(start), "length": "100", "report_types": "[11]", "filer_types": "[]",
            "submitted_start_date": since.strftime("%m/%d/%Y 00:00:00"), "submitted_end_date": "",
            "candidate_state": "", "senator_state": "", "office_id": "", "first_name": "", "last_name": "",
            "csrfmiddlewaretoken": csrf})
        r.raise_for_status(); j = r.json()
        out += j["data"]
        start += 100
        if start >= j["recordsTotal"]:
            return out


def cells(row):
    return [html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c))).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]


def report(link):
    rid = link.rstrip("/").split("/")[-1]
    c = CACHE / f"{rid}.json"
    if c.exists():
        return json.loads(c.read_text())
    paper = "/paper/" in link
    rows = []
    if not paper:
        t = S.get(BASE + link, timeout=60).text
        trs = re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S)
        head = cells(trs[0]) if trs else []
        for tr in trs[1:]:
            v = cells(tr)
            if len(v) == len(head):
                rows.append(dict(zip(head, v)))
        time.sleep(1)
    res = {"id": rid, "paper": paper, "rows": rows}
    c.write_text(json.dumps(res, ensure_ascii=False))
    return res


def main():
    agree()
    since = datetime.date.today() - datetime.timedelta(days=DAYS)
    out = []
    for first, last, full, a, filed in search(since):
        link = re.search(r'href="([^"]+)"', a).group(1)
        r = report(link)
        out.append({"first": first, "last": last, "name": full, "title": re.sub(r"<[^>]+>", "", a), "filed": filed,
                    "url": BASE + link, **r})
    OUT.write_text(json.dumps({"updated": datetime.datetime.utcnow().isoformat(timespec="minutes") + "Z", "reports": out}, ensure_ascii=False, indent=0))
    print(len(out), "reports")


if __name__ == "__main__":
    main()
