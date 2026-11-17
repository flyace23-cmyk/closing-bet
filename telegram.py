"""텔레그램 보내기·받기. 토큰은 GitHub Secrets(환경변수)에서만 읽습니다.
대화방 번호(TELEGRAM_CHAT_ID)를 따로 안 넣으면, 봇에게 메시지를 보낸 사람의 대화방을 자동으로 찾습니다."""
import os, requests

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT = os.environ.get("TELEGRAM_CHAT_ID")


def _raw_updates():
    if not TOKEN:
        return []
    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", timeout=15).json()
    return [u["message"] for u in r.get("result", []) if "message" in u]


def chat_id():
    global CHAT
    if not CHAT:
        msgs = [m for m in _raw_updates() if m["chat"].get("type") == "private"]
        if msgs:
            CHAT = str(msgs[-1]["chat"]["id"])
    return CHAT


def send(text):
    if not TOKEN or not chat_id():
        print("----- (텔레그램 설정 없음: 화면 출력) -----\n" + text)
        return
    for i in range(0, len(text), 3800):
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data=dict(chat_id=CHAT, text=text[i:i + 3800]), timeout=15)


def updates():
    """봇에게 보낸 최근 메시지 (최근 24시간)"""
    cid = chat_id()
    return [m for m in _raw_updates() if str(m["chat"]["id"]) == str(cid)]


if __name__ == "__main__":
    if not TOKEN:
        print("점검: TELEGRAM_TOKEN 비어 있음")
    else:
        me = requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe", timeout=15).json()
        print("점검: 토큰 확인 →", "정상, 봇 아이디 @" + me["result"]["username"] if me.get("ok") else f"실패 ({me.get('description')})")
        raw = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", timeout=15).json()
        print("점검: getUpdates →", raw.get("ok"), raw.get("description", ""), "전체", len(raw.get("result", [])), "건", [list(u.keys()) for u in raw.get("result", [])][:5])
        wh = requests.get(f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo", timeout=15).json()
        print("점검: 웹훅 →", (wh.get("result") or {}).get("url") or "없음")
        print("점검: 봇이 받은 개인 메시지 수 →", len([m for m in _raw_updates() if m["chat"].get("type") == "private"]))
    send("✅ 종가베팅 봇 연결 시험 메시지입니다. 평일 15:10 후보 알림, 19:00 저녁 정리를 보내드려요.")
