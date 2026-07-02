# 국립용지봉자연휴양림 · 숲속의 집 예약 모니터

산림청 숲나들e(foresttrip.go.kr) **월별현황조회**를 주기적으로 조회하여
숙박시설 **`숲속의 집`(12개 객실)** 의 예약가능 날짜를 찾아내고 **디스코드로 알림**한다.

두 가지 알림 방식을 지원한다.

- **봇 보고(`--report`)**: 디스코드 **봇 토큰**으로 채널에 현재 예약가능 현황을 게시.
  `--loop 3600` 과 함께 쓰면 **1시간마다 보고**.
- **웹훅 알림(`--notify`)**: **웹훅**으로 '새로 열린' 예약가능 자리만 알림(상태파일 비교, 중복 방지).

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

# 3) [봇] 채널에 현재 예약가능 현황 게시
export DISCORD_BOT_TOKEN="봇토큰"
export DISCORD_CHANNEL_ID="채널ID"
python foresttrip_monitor.py --report

# 4) [봇] 1시간마다 채널에 보고
python foresttrip_monitor.py --report --loop 3600
#   예약가능이 있을 때만 보고하려면(빈 보고 생략):
python foresttrip_monitor.py --report --only-available --loop 3600

# 5) [웹훅] '새' 예약가능 자리만 즉시 알림 (봇과 독립적으로 병행 가능)
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/xxx/yyy"
python foresttrip_monitor.py --notify --loop 300
```

환경변수 요약:

| 변수 | 용도 |
|------|------|
| `DISCORD_BOT_TOKEN`  | 봇 보고(`--report`)용 봇 토큰 |
| `DISCORD_CHANNEL_ID` | 봇이 게시할 채널 ID |
| `DISCORD_WEBHOOK_URL`| 웹훅 알림(`--notify`)용 URL |

## 디스코드 봇 만들기 (`--report`)

1. https://discord.com/developers/applications → **New Application** 생성
2. 좌측 **Bot** → **Reset Token** 으로 **봇 토큰** 발급·복사 → `DISCORD_BOT_TOKEN`
3. 좌측 **OAuth2 → URL Generator** → scope `bot`, 권한 `Send Messages` 선택 →
   생성된 URL 로 **봇을 서버에 초대**
4. 디스코드에서 **사용자 설정 → 고급 → 개발자 모드 ON** →
   보고받을 **채널 우클릭 → 채널 ID 복사** → `DISCORD_CHANNEL_ID`

> 봇은 게이트웨이(상시 접속) 없이 REST API 로 메시지만 게시하므로 가볍다.
> 봇이 해당 채널에 접근·발언 권한이 있어야 한다.

## 디스코드 웹훅 만들기 (`--notify`)

1. 디스코드 서버 → 채널 설정 ⚙️ → **연동(Integrations)** → **웹후크(Webhooks)**
2. **새 웹후크** 생성 → **웹후크 URL 복사** → `DISCORD_WEBHOOK_URL`

## 리눅스 서버 배포 / 스케줄링

### 1) 코드 받기

```bash
git clone git@github.com:suitable8111/resserve_penson.git ~/Document/python/resserve_penson
cd ~/Document/python/resserve_penson

# 최신 데비안/우분투는 시스템 pip 설치가 막혀 있으므로(PEP 668) venv 사용
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 실행 테스트
.venv/bin/python foresttrip_monitor.py --waitlist
```

> `error: externally-managed-environment` 가 나오면 위처럼 venv 를 쓰면 된다.
> venv 없이 쓰려면 `sudo apt install python3-requests` 또는
> `pip install --break-system-packages -r requirements.txt` 도 가능하다.

### 2-A) systemd (권장 — 상주 프로세스로 1시간마다 봇 보고)

`systemd/foresttrip-monitor.service` 의 `User`, `WorkingDirectory`,
`DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID` 를 서버에 맞게 수정한 뒤:

```bash
sudo cp systemd/foresttrip-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now foresttrip-monitor.service
journalctl -u foresttrip-monitor -f      # 로그 확인
```

### 2-B) cron (1시간마다 단발 실행)

```cron
0 * * * * cd ~/Document/python/resserve_penson && DISCORD_BOT_TOKEN="봇토큰" DISCORD_CHANNEL_ID="채널ID" ~/Document/python/resserve_penson/.venv/bin/python foresttrip_monitor.py --report >> monitor.log 2>&1
```

> systemd 방식은 `--loop` 로 프로세스가 계속 떠 있고, cron 방식은 매번 새로 실행된다.
> 둘 중 하나만 쓰면 된다. 상태파일(`.foresttrip_state.json`)로 웹훅 중복 알림을 막으므로 어느 쪽이든 안전하다.

## 상태 파일

`.foresttrip_state.json` 에 마지막으로 본 예약가능 목록을 저장한다.
같은 자리를 반복 알림하지 않으며, 자리가 사라졌다가 다시 열리면 재알림한다.

## 참고

- 조회 대상 기간: 사이트가 제공하는 **현재월 + 2개월**(예약가능기간 내 날짜만 `예`로 표시됨)
- 객실 goodsId 12개는 코드에 하드코딩되어 있다. 사이트가 객실을 개편하면 갱신 필요.
- 조회는 공개 데이터 열람이며 로그인이 필요 없다. **예약 신청 자체는 사람이 직접** 진행해야 한다.
