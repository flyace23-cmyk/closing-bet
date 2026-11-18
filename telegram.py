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


CHAT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "records", "chat_id.txt")


def chat_id():
    """대화방 번호: 비밀값 → 저장해 둔 파일 → 봇이 받은 최근 메시지(24시간) 순서로 찾음.
    텔레그램은 최근 24시간 메시지만 알려주므로, 한 번 찾으면 파일에 저장해 둔다."""
    global CHAT
    if not CHAT and os.path.exists(CHAT_FILE):
        CHAT = open(CHAT_FILE).read().strip() or None
    if not CHAT:
        msgs = [m for m in _raw_updates() if m["chat"].get("type") == "private"]
        if msgs:
            CHAT = str(msgs[-1]["chat"]["id"])
            os.makedirs(os.path.dirname(CHAT_FILE), exist_ok=True)
            open(CHAT_FILE, "w").write(CHAT)
    return CHAT


def _chunks(text, n=3800):
    """긴 메시지를 빈 줄 기준으로 나눔 (HTML 태그가 중간에 잘리지 않게)"""
    out, cur = [], ""
    for part in text.split("\n\n"):
        while len(part) > n:
            out.append(part[:n]); part = part[n:]
        if cur and len(cur) + len(part) + 2 > n:
            out.append(cur); cur = part
        else:
            cur = f"{cur}\n\n{part}" if cur else part
    if cur:
        out.append(cur)
    return out


def send(text, html=False):
    """html=True 이면 <b>굵게</b>, <pre>줄 맞춤</pre> 같은 텔레그램 서식을 씀"""
    if os.environ.get("PREVIEW"):
        text = "🧪 미리보기 (지금 가격 기준, 실제 알림·기록 아님)\n" + text
    if not TOKEN or not chat_id():
        print("----- (텔레그램 설정 없음: 화면 출력) -----\n" + text)
        return
    for part in _chunks(text):
        data = dict(chat_id=CHAT, text=part)
        if html:
            data["parse_mode"] = "HTML"
        r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=data, timeout=15)
        if html and not r.json().get("ok"):   # 서식 오류면 서식 없이 다시 보냄
            import re as _re
            data.pop("parse_mode"); data["text"] = _re.sub(r"<[^>]+>", "", part).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=data, timeout=15)


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
