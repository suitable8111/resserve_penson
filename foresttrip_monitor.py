#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
국립용지봉자연휴양림 '숲속의 집' 예약가능 모니터 + 디스코드 알림.

산림청 숲나들e(foresttrip.go.kr) 월별현황조회의 내부 JSON API를 그대로 호출해
'숲속의 집' 12개 객실의 날짜별 예약 상태를 조회한다.

상태 판정 규칙(웹 화면의 마크와 1:1 대조하여 검증됨):
    rsrvtAvail == "Y" and rsrvtCnt == 0   -> 예약가능(예)   ← 알림 대상
    rsrvtAvail == "Y" and rsrvtCnt >= 1   -> 대기(대, 순위 = wtngCnt + 1)
    rsrvtAvail == "BEFORE_DATE"           -> 예약/대기 완료(완)
    rsrvtAvail == "PRNSL_DAY"             -> 휴무(휴)
    rsrvtAvail == "NOTOPEN"               -> 아직 예약기간 아님(공/미오픈)

사용 예:
    python foresttrip_monitor.py                 # 현재 예약가능 현황만 출력
    python foresttrip_monitor.py --waitlist      # 대기 가능 현황도 함께 출력
    python foresttrip_monitor.py --notify        # 새 예약가능 발견 시 디스코드 알림(상태파일 비교)
    python foresttrip_monitor.py --loop 300       # 300초 간격으로 반복 실행(+--notify 권장)

디스코드 웹훅은 환경변수 DISCORD_WEBHOOK_URL 로 전달한다.
"""

import argparse
import calendar
import json
import os
import re
import sys
import time
from datetime import datetime

import requests

BASE = "https://www.foresttrip.go.kr"
STATUS_PAGE = BASE + "/rep/or/sssn/monthRsrvtStatus.do?hmpgId=0302&menuId=001004"
AVAIL_API = BASE + "/rep/or/selectRsrvtAvailInfoListForMonthRsrvt.do"
INSTT_ID = "0302"                # 국립용지봉자연휴양림
UPPER_GOODS = "01"               # 숙소
GOODS_CLSSC = "01001"            # 숲속의집

# '숲속의 집' 12개 객실 goodsId (안정적 식별자, 웹페이지에서 추출)
GOODS_IDS = [
    "G03020100101001001000001",  # 1호 (4인/23㎡)
    "G03020100101001001000090",  # 1호 (5인/33㎡)
    "G03020100101001001000002",  # 2호 (4인/23㎡)
    "G03020100101001001000089",  # 2호 (5인/33㎡)
    "G03020100101001001000003",  # 3호 (5인/30㎡)
    "G03020100101001002000004",  # 4호 (5인/30㎡)
    "G03020100101001001000005",  # 5호 (4인/23㎡)
    "G03020100101001001000088",  # 5호 (5인/33㎡)
    "G03020100101001001000006",  # 6호 (4인/23㎡)
    "G03020100101001001000087",  # 6호 (5인/33㎡)
    "G03020100101001001000007",  # 7호 (4인/23㎡)
    "G03020100101001001000086",  # 7호 (5인/33㎡)
]

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".foresttrip_state.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]


class SessionExpired(Exception):
    """서버가 로그인/접근 오류 안내 페이지를 반환한 경우."""


def new_session():
    """휴양림 페이지를 GET 하여 세션 쿠키와 _csrf 토큰을 확보한다.

    이 페이지는 비로그인 상태에서 HTTP 401 을 반환하지만, 본문에는 정상적인
    _csrf 토큰이 들어 있고 조회 API 는 이 세션으로 호출 가능하다. 따라서
    상태코드로 중단하지 않고 본문에서 토큰을 추출한다.
    """
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    })
    r = s.get(STATUS_PAGE, timeout=15)
    m = re.search(r'name="_csrf"[^>]*value="([^"]+)"', r.text) or \
        re.search(r'value="([^"]+)"[^>]*name="_csrf"', r.text)
    if not m:
        raise RuntimeError(
            "페이지에서 _csrf 토큰을 찾지 못했습니다 (HTTP %s). 사이트 구조가 바뀌었을 수 있습니다."
            % r.status_code)
    csrf = m.group(1)
    # 월 선택 옵션은 JS 로 채워져 raw HTML 에 없을 수 있음 -> 비면 호출부에서 계산.
    months = re.findall(r'<option value="(\d{6})"', r.text)
    return s, csrf, months


def month_last_day(yyyymm):
    y, mth = int(yyyymm[:4]), int(yyyymm[4:6])
    return "%04d%02d%02d" % (y, mth, calendar.monthrange(y, mth)[1])


def fetch_month(session, csrf, yyyymm):
    """한 달치 12개 객실의 날짜별 예약 레코드를 반환한다."""
    last_day = month_last_day(yyyymm)
    headers = {
        "Content-Type": "application/json",
        "X-CSRF-TOKEN": csrf,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": STATUS_PAGE,
    }
    records = []
    for i in range(0, len(GOODS_IDS), 5):
        batch = GOODS_IDS[i:i + 5]
        payload = {
            "insttId": INSTT_ID,
            "upperGoodsClsscCd": UPPER_GOODS,
            "goodsIdList": batch,
            "srchDate": yyyymm,
            "lastDay": last_day,
            "inqurSctin": "01",
        }
        r = session.post(AVAIL_API, data=json.dumps(payload), headers=headers, timeout=15)
        ctype = r.headers.get("content-type", "")
        if "json" not in ctype and "알려드립니다" in r.text:
            raise SessionExpired("서버가 로그인/접근 오류 페이지를 반환했습니다.")
        records.extend(r.json())
    return records


def room_label(rec):
    """레코드에서 '숲속의집 4호 (5인/30㎡)' 형태의 표시 이름을 만든다."""
    name = rec.get("goodsNm", "").strip()
    area = (rec.get("insttArea") or "").strip()
    cap = rec.get("mxmmAccptCnt")
    extra = []
    if cap:
        extra.append("%s인" % cap)
    if area:
        extra.append(area)
    return "%s (%s)" % (name, "/".join(extra)) if extra else name


def fmt_date(yyyymmdd):
    d = datetime.strptime(yyyymmdd, "%Y%m%d")
    return "%d-%02d-%02d(%s)" % (d.year, d.month, d.day, WEEKDAY_KR[d.weekday()])


def classify(records):
    """레코드 목록을 예약가능 / 대기가능 두 리스트로 분류한다."""
    available, waitlist = [], []
    for x in records:
        avail = x.get("rsrvtAvail")
        if avail != "Y":
            continue
        cnt = x.get("rsrvtCnt") or 0
        item = {
            "date": x["useDt"],
            "room": room_label(x),
            "wtng": x.get("wtngCnt") or 0,
        }
        if cnt == 0:
            available.append(item)
        else:
            item["rank"] = (x.get("wtngCnt") or 0) + 1
            waitlist.append(item)
    key = lambda it: (it["date"], it["room"])
    return sorted(available, key=key), sorted(waitlist, key=key)


def collect(session, csrf, months):
    all_available, all_waitlist = [], []
    for ym in months:
        recs = fetch_month(session, csrf, ym)
        a, w = classify(recs)
        all_available.extend(a)
        all_waitlist.extend(w)
    return all_available, all_waitlist


def print_report(available, waitlist, show_waitlist):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 60)
    print("국립용지봉자연휴양림 · 숲속의 집 예약현황  (%s)" % now)
    print("=" * 60)
    if available:
        print("\n🟢 예약가능 %d건" % len(available))
        for it in available:
            print("   • %s  %s" % (fmt_date(it["date"]), it["room"]))
    else:
        print("\n🟢 예약가능: 없음")
    if show_waitlist:
        if waitlist:
            print("\n🔵 대기가능 %d건" % len(waitlist))
            for it in waitlist:
                print("   • %s  %s  (대기 %d순위)" % (fmt_date(it["date"]), it["room"], it["rank"]))
        else:
            print("\n🔵 대기가능: 없음")
    print()


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def save_state(keys):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(keys), f, ensure_ascii=False, indent=1)


def send_discord(webhook, new_slots):
    lines = ["@here 🏕️ **국립용지봉자연휴양림 · 숲속의 집 예약가능 알림!**", ""]
    for it in new_slots:
        lines.append("🟢 **%s** — %s" % (fmt_date(it["date"]), it["room"]))
    lines.append("")
    lines.append("예약 바로가기: %s" % STATUS_PAGE)
    payload = {"content": "\n".join(lines)}
    r = requests.post(webhook, json=payload, timeout=15)
    r.raise_for_status()


def notify(available, webhook):
    """이전에 못 봤던 새 예약가능 건만 디스코드로 알린다."""
    seen = load_state()
    current = {"%s|%s" % (it["date"], it["room"]): it for it in available}
    new_keys = [k for k in current if k not in seen]
    if new_keys:
        new_slots = [current[k] for k in sorted(new_keys)]
        if webhook:
            send_discord(webhook, new_slots)
            print("📨 디스코드 알림 전송: 새 예약가능 %d건" % len(new_slots))
        else:
            print("⚠️  DISCORD_WEBHOOK_URL 미설정 — 알림 생략. 새 예약가능 %d건:" % len(new_slots))
            for it in new_slots:
                print("   • %s  %s" % (fmt_date(it["date"]), it["room"]))
    else:
        print("변동 없음 (새 예약가능 건 없음).")
    # 상태 저장: 현재 예약가능한 것만 기억 -> 사라졌다가 다시 나오면 재알림
    save_state(current.keys())


def run_once(args, webhook):
    session, csrf, months = new_session()
    if not months:
        # 페이지에서 월 목록을 못 얻으면 현재월부터 3개월 계산
        now = datetime.now()
        months = []
        y, m = now.year, now.month
        for _ in range(3):
            months.append("%04d%02d" % (y, m))
            m += 1
            if m > 12:
                m, y = 1, y + 1
    available, waitlist = collect(session, csrf, months)
    if args.notify:
        print_report(available, waitlist, args.waitlist)
        notify(available, webhook)
    else:
        print_report(available, waitlist, args.waitlist)
    return available


def main():
    p = argparse.ArgumentParser(description="국립용지봉자연휴양림 숲속의 집 예약 모니터")
    p.add_argument("--waitlist", action="store_true", help="대기가능 현황도 함께 출력")
    p.add_argument("--notify", action="store_true", help="새 예약가능 발견 시 디스코드 알림")
    p.add_argument("--loop", type=int, metavar="SEC", help="주어진 초 간격으로 반복 실행")
    args = p.parse_args()

    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

    def cycle():
        try:
            run_once(args, webhook)
        except SessionExpired as e:
            print("❌ 세션/접근 오류: %s" % e, file=sys.stderr)
        except requests.RequestException as e:
            print("❌ 네트워크 오류: %s" % e, file=sys.stderr)

    if args.loop:
        print("🔁 %d초 간격 모니터링 시작 (Ctrl+C 로 종료)" % args.loop)
        while True:
            cycle()
            time.sleep(args.loop)
    else:
        cycle()


if __name__ == "__main__":
    main()
