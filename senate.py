"""미국 상원 의원 주식 거래 신고(PTR) 수집 — GitHub Actions(미국 서버)에서 매일 돈다.

상원 공시 사이트(efdsearch.senate.gov)는 한국 서버 접속을 막아서, 미국에서 받아 이 저장소에 JSON 으로 둔다.
블로그 서버는 raw.githubusercontent.com 에서 data/senate_ptr.json 만 읽는다.

출력: data/senate_ptr.json — 최근 120일 신고서 목록과 거래 줄
"""
import json, re, html, time, datetime, sys
from pathlib import Path
import requests

BASE = "https://efdsearch.senate.gov"
OUT = Path("data/senate_ptr.json")
CACHE = Path("data/reports"); CACHE.mkdir(parents=True, exist_ok=True)
DAYS = 120
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (research; github.com senate-ptr)"
STATUS = Path("data/status.json")   # 서버(NAS) 순찰이 읽는다 — 실패해도 GitHub 메일 대신 여기 남기고 고PD 우편함으로(2026-10-18)


def _req(method, url, **kw):
    """상원 사이트는 점검·일시 장애가 잦다(2026-10-18 일요일 아침 첫 접속에서 7초 만에 실패) → 20·40·80초 쉬며 4번까지."""
    last = None
    for k in range(4):
        try:
            r = S.request(method, url, timeout=60, **kw)
            if r.status_code < 400:
                return r
            last = f"HTTP {r.status_code} {url} {r.text[:200]!r}"
        except requests.RequestException as e:
            last = f"{type(e).__name__} {url} {e}"[:300]
        print("다시:", last, flush=True)
        if k < 3:
            time.sleep(20 * 2 ** k)
    raise RuntimeError(last)


def agree():
    r = _req("GET", BASE + "/search/home/")
    m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', r.text)
    if not m:                                   # 동의 페이지 모양이 바뀌었거나 점검 화면
        raise RuntimeError("동의 페이지에 csrf 가 없음: " + re.sub(r"\s+", " ", r.text)[:300])
    _req("POST", BASE + "/search/home/", data={"prohibition_agreement": "1", "csrfmiddlewaretoken": m.group(1)},
         headers={"Referer": BASE + "/search/home/"})


def search(since):
    out, start = [], 0
    while True:
        csrf = S.cookies.get("csrftoken")
        r = _req("POST", BASE + "/search/report/data/", headers={"Referer": BASE + "/search/", "X-CSRFToken": csrf}, data={
            "start": str(start), "length": "100", "report_types": "[11]", "filer_types": "[]",
            "submitted_start_date": since.strftime("%m/%d/%Y 00:00:00"), "submitted_end_date": "",
            "candidate_state": "", "senator_state": "", "office_id": "", "first_name": "", "last_name": "",
            "csrfmiddlewaretoken": csrf})
        j = r.json()
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
        t = _req("GET", BASE + link).text
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
    return len(out)


if __name__ == "__main__":
    now = datetime.datetime.utcnow().isoformat(timespec="minutes") + "Z"
    try:
        n = main()
        STATUS.write_text(json.dumps({"ok": True, "at": now, "reports": n}, ensure_ascii=False))
    except Exception as e:   # 끝내 실패해도 GitHub 실패 메일 대신 상태 파일로(서버 순찰 → 고PD 우편함). 지난 자료(senate_ptr.json)는 그대로
        STATUS.write_text(json.dumps({"ok": False, "at": now, "error": f"{type(e).__name__}: {e}"[:600]}, ensure_ascii=False))
        print("실패 — data/status.json 에 남김:", e, flush=True)
