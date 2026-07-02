#!/usr/bin/env bash
#
# systemd 유닛을 현재 사용자/경로에 맞게 자동 생성·등록한다.
# 사용법:  ./install.sh [보고간격초]      (기본 3600 = 1시간)
# 예)     ./install.sh 300               (5분마다 보고)
#
set -euo pipefail

INTERVAL="${1:-120}"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
ENVFILE="$APP_DIR/foresttrip.env"
SERVICE="/etc/systemd/system/foresttrip-monitor.service"

echo "▶ 앱 경로 : $APP_DIR"
echo "▶ 실행 계정: $USER"
echo "▶ 보고 간격: ${INTERVAL}초"

# 1) venv + 의존성
if [ ! -d "$APP_DIR/.venv" ]; then
  echo "▶ venv 생성..."
  python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

# 2) 비밀값 파일(foresttrip.env) 준비 — 여기에 토큰/채널ID 를 넣는다
if [ ! -f "$ENVFILE" ]; then
  cp "$APP_DIR/foresttrip.env.example" "$ENVFILE"
  chmod 600 "$ENVFILE"
  echo "⚠ 생성됨: $ENVFILE"
  echo "  → 이 파일을 열어 DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID 를 채운 뒤 다시 실행하세요."
  echo "    nano $ENVFILE"
  exit 0
fi

# 3) systemd 유닛 생성(현재 사용자/절대경로/비밀파일 자동 반영)
sudo tee "$SERVICE" >/dev/null <<UNIT
[Unit]
Description=국립용지봉자연휴양림 숲속의 집 예약 모니터 (Discord 봇 보고)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENVFILE
# 로그가 journal 에 실시간으로 찍히도록 출력 버퍼링 끔
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP_DIR/.venv/bin/python -u $APP_DIR/foresttrip_monitor.py --report --new-only --loop $INTERVAL
Restart=on-failure
RestartSec=60

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
echo "✅ 등록 완료: $SERVICE"
echo "   시작:  sudo systemctl enable --now foresttrip-monitor.service"
echo "   로그:  journalctl -u foresttrip-monitor -f"
