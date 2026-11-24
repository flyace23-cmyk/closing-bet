"""장전 뉴스 브리핑 보내기 — Claude 예약 작업이 records/briefing/날짜.md 를 올리면 GitHub이 이 파일을 실행

받는 방: '같이 보는 방'(아버지와 공유하는 텔레그램 단체방)
  1) 비밀값 TELEGRAM_SHARE_CHAT_ID (있으면)
  2) records/share_chat_id.txt (한 번 찾으면 저장)
  3) 봇이 최근 24시간에 받은 단체방 메시지에서 자동으로 찾기 → 단체방에서 /start 한 번 보내면 됨
  못 찾으면 정훈 개인 방으로 보내고 "단체방에 /start 보내기" 안내를 붙임
같은 날 두 번 보내지 않음 (records/briefing/sent_날짜.txt)
"""
import os, sys, requests
import telegram as tg

ROOT = os.path.dirname(os.path.abspath(__file__))
SHARE_FILE = os.path.join(ROOT, "records", "share_chat_id.txt")


def share_chat():
    c = os.environ.get("TELEGRAM_SHARE_CHAT_ID")
    if c:
        return c
    if os.path.exists(SHARE_FILE):
        c = open(SHARE_FILE).read().strip()
        if c:
            return c
    if not tg.TOKEN:
        return None
    try:
        r = requests.get(f"https://api.telegram.org/bot{tg.TOKEN}/getUpdates", timeout=15).json()
    except Exception:
        return None
    groups = []
    for u in r.get("result", []):
        for k in ("message", "my_chat_member", "channel_post"):
            m = u.get(k)
            if m and m.get("chat", {}).get("type") in ("group", "supergroup"):
                groups.append(str(m["chat"]["id"]))
    if groups:
        c = groups[-1]
        open(SHARE_FILE, "w").write(c)
        return c
    return None


def post(chat, text):
    for part in tg._chunks(text):
        requests.post(f"https://api.telegram.org/bot{tg.TOKEN}/sendMessage",
                      data=dict(chat_id=chat, text=part, disable_web_page_preview="true"), timeout=15)


def main():
    import market_data as md
    day = sys.argv[1] if len(sys.argv) > 1 else md.today()
    path = os.path.join(ROOT, "records", "briefing", f"{day}.md")
    sent = os.path.join(ROOT, "records", "briefing", f"sent_{day}.txt")
    if not os.path.exists(path):
        print("오늘 브리핑 파일 없음:", path); return
    if os.path.exists(sent) and "--force" not in sys.argv:
        print("이미 보냄"); return
    text = open(path, encoding="utf-8").read().strip()
    if not text or text.startswith("SKIP"):
        print("보낼 내용 없음"); return
    if not tg.TOKEN:
        print(text); return
    chat = share_chat()
    if not chat:
        chat = tg.chat_id()
        text += "\n\n⚙️ 같이 보는 방을 아직 못 찾아서 개인 방으로 보냈어요. 같이 보는 방에서 /start 를 한 번 보내 주세요."
    post(chat, text)
    tg._archive(text, False)
    open(sent, "w").write(f"{chat}\n")
    print("보냄:", chat)


if __name__ == "__main__":
    main()
