"""에이블: KT AIVLE School 미니 프로젝트 3차 (2일차).
어제의 이미지 통합(3) -> 구조화 분석(1) -> 우선순위 브리핑(2) 워크플로를 Streamlit에 통합.
"""
import os
import re
import json
import base64
import smtplib
from datetime import datetime, date
from zoneinfo import ZoneInfo
from email.message import EmailMessage

import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="에이블 | AI 개인비서", page_icon="🤖", layout="wide")

# Streamlit Cloud Secrets는 자동 환경 변수 주입이 가능한 설정이지만,
# 로컬/배포 환경 모두를 위해 안전하게 명시적으로 로드합니다.
def config(key):
    value = os.getenv(key)
    if value:
        return value
    try:
        return st.secrets.get(key)
    except (FileNotFoundError, KeyError):
        return None

api_key = config("OPENAI_API_KEY")
if not api_key:
    st.error("OPENAI_API_KEY를 Streamlit Secrets에 등록해주세요.")
    st.stop()
client = OpenAI(api_key=api_key)
MODEL = "gpt-4.1-mini"

ROLE = """당신은 KT AIVLE School 출신 김 대리의 한국어 AI 개인비서 '에이블'입니다.
친절하고 명확하게 답하세요. 회의 내용에서 결정사항과 검토사항을 구분하고,
김 대리의 담당 업무/기한을 정확히 확인하세요. 근거 없는 업무나 날짜를 만들지 마세요.
미확정이거나 충돌하는 내용은 '확인 필요'라고 표시하세요.
사용자가 명확하게 이메일 발송을 지시하지 않았다면 이메일 발송을 제안하거나 실행하지 마세요.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "decisions": {"type": "array", "items": {"type": "string"}},
        "pending": {"type": "array", "items": {"type": "string"}},
        "tasks": {"type": "array", "items": {
            "type": "object", "properties": {
                "task": {"type": "string"}, "owner": {"type": "string"},
                "due_date": {"type": ["string", "null"]},
                "importance": {"type": "string", "enum": ["높음", "보통", "낮음", "미정"]},
                "details": {"type": "string"}
            },
            "required": ["task", "owner", "due_date", "importance", "details"],
            "additionalProperties": False
        }}
    },
    "required": ["summary", "decisions", "pending", "tasks"],
    "additionalProperties": False
}


def ask_llm(question, instructions=ROLE):
    result = client.responses.create(model=MODEL, instructions=instructions, input=question)
    return result.output_text


def image_to_analysis(blob, mime):
    """어제 기능 3: 이미지에서 글자/결정/담당/마감 정보 추출."""
    if mime not in ("image/jpeg", "image/png", "image/webp"):
        raise ValueError("JPG, PNG, WEBP 이미지만 지원합니다.")
    b64 = base64.b64encode(blob).decode("ascii")
    output = client.responses.create(
        model=MODEL,
        instructions=(ROLE + "\n화이트보드/슬라이드의 핵심 텍스트, 결정사항, 담당자, 기한,"
                      "판독 불명확 부분을 구분하여 기술하세요. 추측 금지."),
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": "회의 이미지 정보를 읽어 요약해 주세요."},
            {"type": "input_image", "image_url": f"data:{mime};base64,{b64}", "detail": "high"}
        ]}]
    )
    return output.output_text


def integrate_meeting(meeting_text, image_analysis=""):
    """어제 기능 3: 회의록 + 이미지 분석 통합."""
    if not image_analysis:
        return meeting_text
    return ask_llm(
        "원본 회의록과 화이트보드 사진 정보를 통합하세요.\n"
        "1. 통합 회의 요약 2. 확정된 주요 결정사항 3. 담당자별 업무 4. 업무 기한 "
        "5. 사진 추가 정보 6. 확인 필요 사항.\n"
        "중복을 제거하고 충돌하는 날짜, KPI, 담당자를 확인 필요로 분류하세요.\n"
        "사진으로 확정 여부를 알 수 없는 정보는 확정하지 마세요.\n\n"
        f"[원본 회의록]\n{meeting_text}\n\n[이미지 분석]\n{image_analysis}"
    )


def analyze_meeting(meeting_text):
    """어제 기능 1: JSON Schema 기반 요약/결정/미확정/업무 추출."""
    result = client.responses.create(
        model=MODEL, instructions=(ROLE + "\nJSON으로 요약/결정/보류/담당자별 업무를 추출하세요. "
                                   "명확한 날짜만 YYYY-MM-DD, 불명확하면 null, 중요도 불분명 시 미정."),
        input=f"다음 회의록을 분석하세요:\n\n{meeting_text}",
        text={"format": {"type": "json_schema", "name": "meeting_analysis",
                         "schema": SCHEMA, "strict": True}}
    )
    return json.loads(result.output_text)


def calculate_priority(task):
    """어제 기능 2: 원래 우선순위 계산 규칙을 그대로 사용."""
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    score = 0
    due_date = task.get("due_date")
    if due_date:
        try:
            days_left = (date.fromisoformat(due_date) - today).days
            if days_left < 0: score += 100
            elif days_left == 0: score += 90
            elif days_left == 1: score += 70
            elif days_left <= 3: score += 50
            elif days_left <= 7: score += 25
        except (ValueError, TypeError):
            pass
    score += {"높음": 30, "보통": 15, "낮음": 0, "미정": 0}.get(task.get("importance"), 0)
    return score


def create_briefing(analysis):
    """어제 기능 2: 김 대리 담당 업무만 우선순위 정렬 후 브리핑."""
    my_tasks = [dict(t) for t in analysis.get("tasks", [])
                if "김대리" in t.get("owner", "").replace(" ", "")]
    for t in my_tasks:
        t["priority"] = calculate_priority(t)
    my_tasks.sort(key=lambda x: x["priority"], reverse=True)
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    briefing = ask_llm(
        f"오늘은 {today}입니다. 아래 김 대리 업무만 기준으로 브리핑하세요.\n"
        "1. 지금 우선 처리 2. 오늘 마감 3. 이번 주 준비 4. 기한 확인 필요 5. 요약.\n"
        "오늘 착수 권장과 오늘 마감을 구분하고 완료했다고 추측하지 마세요.\n"
        f"업무: {json.dumps(my_tasks, ensure_ascii=False)}"
    )
    return my_tasks, briefing


def transcribe(audio):
    """어제 미션 4/6: 음성 파일 -> STT."""
    return client.audio.transcriptions.create(model="gpt-4o-mini-transcribe", file=audio).text


def synthesize(text):
    """어제 미션 5/6: TTS 결과를 Streamlit용 바이트로 변환."""
    response = client.audio.speech.create(
        model="tts-1", voice="nova", input=text[:4000], response_format="mp3"
    )
    return response.content


def send_email(to, subject, body):
    """어제 미션 1/7: Gmail SMTP로 실제 발송. 사용자의 확인 버튼 뒤에만 호출."""
    sender, password = config("GMAIL_ADDRESS"), config("GMAIL_APP_PASSWORD")
    if not sender or not password:
        return {"status": "failed", "error": "이메일 Secrets가 없습니다."}
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", to or ""):
        return {"status": "failed", "error": "수신자 주소가 올바르지 않습니다."}
    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"], msg["From"], msg["To"] = subject, sender, to
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(sender, password)
            smtp.send_message(msg)
        return {"status": "success"}
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}


EMAIL_TOOL = [{
    "type": "function", "name": "send_email",
    "description": "사용자가 명시적으로 요청한 이메일 내용을 작성하여 발송을 제안합니다."
                   "앱이 실제 발송 전 확인을 요구합니다.",
    "parameters": {"type": "object", "properties": {
        "to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
        "required": ["to", "subject", "body"], "additionalProperties": False},
    "strict": True
}]


def chat(question):
    """어제 미션 7 도구 호출 + 최근 10턴 멀티턴 대화.
    이메일은 LLM이 초안을 만들 뿐, 승인 버튼 전에는 SMTP 호출 금지.
    """
    context = ROLE
    if st.session_state.final_meeting:
        context += "\n[현재 회의록]\n" + st.session_state.final_meeting[:30000]
    if st.session_state.analysis:
        context += "\n[구조화 분석]\n" + json.dumps(st.session_state.analysis, ensure_ascii=False)
    history = []
    for turn in st.session_state.history[-10:]:
        history += [{"role": "user", "content": turn["user"]},
                    {"role": "assistant", "content": turn["assistant"]}]
    history.append({"role": "user", "content": question})
    result = client.responses.create(
        model=MODEL, instructions=context, input=history, tools=EMAIL_TOOL,
        tool_choice="auto", parallel_tool_calls=False
    )
    calls = [x for x in result.output if x.type == "function_call" and x.name == "send_email"]
    if calls:
        # 확인 화면을 만든 뒤에만 발송. 수신자/제목/본문 검토.
        try:
            args = json.loads(calls[0].arguments)
            if not all(args.get(k) for k in ("to", "subject", "body")):
                return "이메일 수신자, 제목 또는 내용이 누락됐습니다. 정보를 알려주세요."
            st.session_state.pending_email = args
            return f"{args['to']} 주소로 보낼 이메일 초안을 준비했습니다. 아래에서 내용을 확인하고 발송 버튼을 눌러주세요."
        except (ValueError, KeyError, TypeError):
            return "이메일 초안을 만들지 못했습니다. 다시 요청해주세요."
    return result.output_text or "답변을 생성하지 못했습니다."


# ------------------------------ UI ------------------------------
st.markdown("""<style>
.block-container {padding-top: 1.4rem;}
[data-testid="stMetric"] {background:#f2f7fa; padding:12px; border-radius:12px;}
</style>""", unsafe_allow_html=True)

for key, default in {
    "history": [], "final_meeting": "", "analysis": None, "my_tasks": [],
    "briefing": "", "image_analysis": "", "pending_email": None,
    "last_transcript": "", "last_audio": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

with st.sidebar:
    st.header("🤖 에이블")
    st.caption("김 대리 전담 AI 개인비서")
    st.image("https://raw.githubusercontent.com/Jangrae/img/master/ai_robot.png", width=160)
    st.info("회의록 + 화이트보드 → 업무 분석 → 우선순위 브리핑")
    if st.button("🗑️ 대화 기록 초기화", use_container_width=True):
        st.session_state.history = []
        st.session_state.pending_email = None
        st.session_state.last_audio = None
        st.rerun()
    st.caption(f"대화 기록: {len(st.session_state.history)} / 10턴")

st.title("에이블 · AI 개인비서")
st.caption("회의 분석 · 업무 우선순위 · 음성 명령 · 이메일 발송")
tab_meeting, tab_chat, tab_tasks = st.tabs(["📑 회의록 분석", "💬 AI 비서 대화", "📌 업무 브리핑"])

with tab_meeting:
    st.subheader("회의 자료 업로드")
    st.write("어제 사용한 `test.txt`, `whiteboard.png` 또는 다른 회의 자료를 업로드하세요.")
    notes = st.file_uploader("회의록 TXT", type=["txt"], key="notes")
    board = st.file_uploader("화이트보드/슬라이드 이미지 (선택)",
                             type=["png", "jpg", "jpeg", "webp"], key="board")
    if st.button("✨ 회의 통합 분석 실행", type="primary", disabled=notes is None):
        try:
            raw = notes.getvalue()
            try:
                meeting_text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                meeting_text = raw.decode("cp949")
            if not meeting_text.strip():
                st.warning("회의록 내용이 비어 있습니다.")
            else:
                with st.spinner("회의 자료를 분석하고 있습니다..."):
                    image_analysis = image_to_analysis(board.getvalue(), board.type) if board else ""
                    final_meeting = integrate_meeting(meeting_text, image_analysis)
                    analysis = analyze_meeting(final_meeting)
                    tasks, briefing = create_briefing(analysis)
                st.session_state.image_analysis = image_analysis
                st.session_state.final_meeting = final_meeting
                st.session_state.analysis = analysis
                st.session_state.my_tasks = tasks
                st.session_state.briefing = briefing
                st.success("통합 분석과 업무 브리핑을 완료했습니다.")
        except Exception as exc:
            st.error(f"분석 실패: {exc}")

    if st.session_state.final_meeting:
        with st.expander("최종 통합 회의록", expanded=True):
            st.write(st.session_state.final_meeting)
        if st.session_state.image_analysis:
            with st.expander("이미지 분석 상세"):
                st.write(st.session_state.image_analysis)
        st.download_button("📥 통합 회의록 다운로드", st.session_state.final_meeting,
                           file_name="final_meeting.txt", mime="text/plain")
    if st.session_state.analysis:
        info = st.session_state.analysis
        col1, col2, col3 = st.columns(3)
        col1.metric("추출 업무", len(info["tasks"]))
        col2.metric("확정 결정", len(info["decisions"]))
        col3.metric("확인 필요", len(info["pending"]))
        st.markdown("#### 회의 핵심 요약")
        st.write(info["summary"])
        st.markdown("#### 확정 결정사항")
        for item in info["decisions"]:
            st.write("•", item)
        st.markdown("#### 확인 필요")
        for item in info["pending"]:
            st.write("•", item)
        st.download_button("📥 구조화 JSON 다운로드",
                           json.dumps(info, ensure_ascii=False, indent=2),
                           file_name="meeting_analysis.json", mime="application/json")

with tab_chat:
    st.subheader("에이블과 대화하기")
    for turn in st.session_state.history:
        with st.chat_message("user"):
            st.write(turn["user"])
        with st.chat_message("assistant"):
            st.write(turn["assistant"])
    typed = st.chat_input("에이블, 오늘 가장 급한 업무가 뭐야?")
    recorded = st.audio_input("🎙️ 음성으로 요청하기")
    voice_clicked = st.button("음성 명령 실행", disabled=recorded is None)
    request = typed
    if voice_clicked and recorded is not None:
        try:
            with st.spinner("음성을 텍스트로 변환 중..."):
                request = transcribe(("recording.wav", recorded.getvalue(), "audio/wav"))
            st.session_state.last_transcript = request
        except Exception as exc:
            st.error(f"음성 인식 실패: {exc}")
    if st.session_state.last_transcript:
        st.info("🎤 최근 음성 인식 결과: " + st.session_state.last_transcript)
    if request:
        try:
            with st.spinner("에이블이 답변 준비 중..."):
                reply = chat(request)
                st.session_state.history.append({"user": request, "assistant": reply})
                st.session_state.history = st.session_state.history[-10:]
                st.session_state.last_audio = None
                # 교안 61p 음성 즉시 재생: 음성 요청이나 음성 답변 활성화 때 자동 생성
                if voice_clicked or st.session_state.get("voice_always", False):
                    st.session_state.last_audio = synthesize(reply)
            st.rerun()
        except Exception as exc:
            st.error(f"요청 처리 실패: {exc}")
    st.toggle("🔊 텍스트 질문에도 음성 응답", key="voice_always")
    if st.session_state.history:
        if st.button("🔈 마지막 답변 음성 생성"):
            try:
                st.session_state.last_audio = synthesize(st.session_state.history[-1]["assistant"])
            except Exception as exc:
                st.error(f"음성 생성 실패: {exc}")
    if st.session_state.last_audio:
        st.audio(st.session_state.last_audio, format="audio/mp3", autoplay=True)

    if st.session_state.pending_email:
        email = st.session_state.pending_email
        st.divider()
        st.subheader("✉️ 이메일 발송 전 확인")
        st.warning("아직 발송되지 않았습니다. 수신자와 내용을 확인한 뒤 발송하세요.")
        with st.form("email_confirm"):
            to = st.text_input("수신자", value=email["to"])
            subject = st.text_input("제목", value=email["subject"])
            body = st.text_area("본문", value=email["body"], height=180)
            confirm = st.form_submit_button("✅ 확인 후 실제 발송")
        if confirm:
            outcome = send_email(to, subject, body)
            if outcome["status"] == "success":
                st.success("이메일을 발송했습니다.")
                st.session_state.pending_email = None
            else:
                st.error("이메일 발송 실패: " + outcome["error"])
        if st.button("❌ 발송 취소"):
            st.session_state.pending_email = None
            st.rerun()

with tab_tasks:
    st.subheader("김 대리 업무 우선순위")
    if st.session_state.analysis is None:
        st.info("먼저 '회의록 분석' 탭에서 회의 자료를 분석해주세요.")
    else:
        tasks = st.session_state.my_tasks
        if tasks:
            rows = [{"순위": i, "업무": t["task"], "담당자": t["owner"],
                     "마감일": t.get("due_date") or "미정", "중요도": t["importance"],
                     "우선순위 점수": t["priority"], "상세": t["details"]}
                    for i, t in enumerate(tasks, 1)]
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("회의록에서 김 대리에게 명시적으로 배정된 업무를 찾지 못했습니다.")
        st.markdown("#### 오늘의 업무 브리핑")
        st.write(st.session_state.briefing)
        if st.button("🔊 업무 브리핑 듣기"):
            try:
                st.audio(synthesize(st.session_state.briefing), format="audio/mp3", autoplay=True)
            except Exception as exc:
                st.error(f"브리핑 음성 생성 실패: {exc}")
