# 국립용지봉자연휴양림 · 숲속의 집 예약 모니터

산림청 숲나들e(foresttrip.go.kr) **월별현황조회**를 주기적으로 조회하여
숙박시설 **`숲속의 집`(12개 객실)** 의 예약가능 날짜를 찾아내고,
새로 열린 자리를 **디스코드로 알림**한다.

## 동작 방식

웹페이지가 내부적으로 호출하는 JSON API
`selectRsrvtAvailInfoListForMonthRsrvt.do` 를 그대로 호출한다. (넷퍼넬 대기열 불필요,
CSRF 토큰만 필요하며 이는 페이지 접속 시 자동 획득)

상태 판정 규칙(웹 화면 마크와 1:1 대조하여 검증):

| API 응답 | 화면 마크 | 의미 |
|----------|-----------|------|
| `rsrvtAvail=="Y"` **및** `rsrvtCnt==0` | 예 | 🟢 **예약가능** (알림 대상) |
| `rsrvtAvail=="Y"` 및 `rsrvtCnt>=1` | 대 | 대기 (순위 = `wtngCnt`+1) |
| `rsrvtAvail=="BEFORE_DATE"` | 완 | 예약/대기 완료 |
| `rsrvtAvail=="PRNSL_DAY"` | 휴 | 휴무 |
| `rsrvtAvail=="NOTOPEN"` | 공 | 아직 예약기간 아님 |

## 설치

```bash
pip install -r requirements.txt
```

## 사용법

```bash
# 1) 현재 예약가능 현황만 출력
python foresttrip_monitor.py

# 2) 대기가능 현황까지 함께 출력
python foresttrip_monitor.py --waitlist

# 3) 새 예약가능 발견 시 디스코드 알림 (상태파일과 비교, 신규만 알림)
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/xxx/yyy"
python foresttrip_monitor.py --notify

# 4) 300초(5분)마다 반복 모니터링 + 알림
python foresttrip_monitor.py --notify --loop 300
```

## 디스코드 웹훅 만들기

1. 디스코드 서버 → 채널 설정 ⚙️ → **연동(Integrations)** → **웹후크(Webhooks)**
2. **새 웹후크** 생성 → **웹후크 URL 복사**
3. 위 `DISCORD_WEBHOOK_URL` 환경변수에 붙여넣기

## 리눅스 서버 배포 / 스케줄링

### 1) 코드 받기

```bash
git clone git@github.com:suitable8111/resserve_penson.git /opt/resserve_penson
cd /opt/resserve_penson

# 최신 데비안/우분투는 시스템 pip 설치가 막혀 있으므로(PEP 668) venv 사용
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 실행 테스트
.venv/bin/python foresttrip_monitor.py --waitlist
```

> `error: externally-managed-environment` 가 나오면 위처럼 venv 를 쓰면 된다.
> venv 없이 쓰려면 `sudo apt install python3-requests` 또는
> `pip install --break-system-packages -r requirements.txt` 도 가능하다.

### 2-A) systemd (권장 — 상주 프로세스로 5분마다 반복)

`systemd/foresttrip-monitor.service` 의 `User`, `WorkingDirectory`,
`DISCORD_WEBHOOK_URL` 을 서버에 맞게 수정한 뒤:

```bash
sudo cp systemd/foresttrip-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now foresttrip-monitor.service
journalctl -u foresttrip-monitor -f      # 로그 확인
```

### 2-B) cron (5분마다 단발 실행)

```cron
*/5 * * * * cd /opt/resserve_penson && DISCORD_WEBHOOK_URL="https://..." /opt/resserve_penson/.venv/bin/python foresttrip_monitor.py --notify >> monitor.log 2>&1
```

> systemd 방식은 `--loop` 로 프로세스가 계속 떠 있고, cron 방식은 매번 새로 실행된다.
> 둘 중 하나만 쓰면 된다. 상태파일(`.foresttrip_state.json`)로 중복 알림을 막으므로 어느 쪽이든 안전하다.

## 상태 파일

`.foresttrip_state.json` 에 마지막으로 본 예약가능 목록을 저장한다.
같은 자리를 반복 알림하지 않으며, 자리가 사라졌다가 다시 열리면 재알림한다.

## 참고

- 조회 대상 기간: 사이트가 제공하는 **현재월 + 2개월**(예약가능기간 내 날짜만 `예`로 표시됨)
- 객실 goodsId 12개는 코드에 하드코딩되어 있다. 사이트가 객실을 개편하면 갱신 필요.
- 조회는 공개 데이터 열람이며 로그인이 필요 없다. **예약 신청 자체는 사람이 직접** 진행해야 한다.
