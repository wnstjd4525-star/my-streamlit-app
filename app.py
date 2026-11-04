
import os, base64, json, requests
import streamlit as st
from openai import OpenAI
 
# 이메일 발송을 위한 라이브러리
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr
import re


# OpenAI 클라이언트 생성
client = OpenAI()

# 이메일 발송 함수 (1일차 미션 1 재사용)
def send_email(to, subject, body):

    sender = os.getenv("GMAIL_ADDRESS")
    password = os.getenv("GMAIL_APP_PASSWORD")

    # 이메일 설정 확인
    if not sender or not password:
        return {
            "status": "failed",
            "error": "Gmail 환경변수가 설정되지 않았습니다."
        }

    # 이메일 구성
    msg = MIMEText(body, "plain", "utf-8")

    msg["Subject"] = str(Header(subject, "utf-8"))
    msg["From"] = formataddr(("AIVLE", sender))
    msg["To"] = to

    try:
        # Gmail SMTP 서버 연결
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(sender, password)

            # 이메일 발송
            smtp.sendmail(
                sender,
                [to],
                msg.as_string()
            )

        return {
            "status": "success",
            "message": "이메일 발송 완료"
        }

    except Exception as e:
        return {
            "status": "failed",
            "error": str(e)
        }


# 페이지 설정
st.set_page_config(page_title="음성 AI 서비스", page_icon="🤖", layout="wide")
st.title("음성 인식 AI 서비스")
st.write("음성으로 질문하시면 답변해 드립니다.")


# 역할 지정
sys_role = """
당신은 KT AIVLE School에서 개발한
AI 개인비서 '에이블(AIVLE)'입니다.

당신의 사용자는 마케팅 및 데이터 분석 업무를
담당하는 '김 대리'입니다.

[주요 역할]
1. 회의록을 분석하고 핵심 내용을 요약합니다.
2. 김 대리에게 배정된 업무를 추출합니다.
3. 업무의 마감일과 우선순위를 정리합니다.
4. 사용자의 질문에 정확하게 답변합니다.
5. 요청이 있을 경우 회의 내용을 이메일로 전달합니다.
6. 업무 진행 상황을 고려하여 할 일을 브리핑합니다.

[응답 규칙]
- 항상 한국어로 답변합니다.
- 사용자를 '김 대리님'이라고 부릅니다.
- 간결하고 전문적인 말투를 사용합니다.
- 회의록에 없는 정보는 임의로 생성하지 않습니다.
- 불확실한 내용은 추정이라고 명시합니다.
- 이메일 발송은 명시적인 요청과 확인이 있을 때만 수행합니다.
"""

# 이메일 발송 도구 정의
email_tools = [
    {
        "type": "function",
        "name": "send_email",
        "description": (
            "사용자가 명시적으로 이메일 발송을 요청한 경우, "
            "회의록 요약 또는 담당 업무 정리 내용을 "
            "이메일로 보내기 위한 초안을 작성합니다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "이메일 수신자 주소"
                },
                "subject": {
                    "type": "string",
                    "description": "이메일 제목"
                },
                "body": {
                    "type": "string",
                    "description": "이메일 본문"
                }
            },
            "required": ["to", "subject", "body"],
            "additionalProperties": False
        },
        "strict": True
    }
]

# 상태 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []

# 지시 영역
with st.form("task_form"):

    uploaded_file = st.file_uploader(
        "회의록 업로드",
        type=["txt"]
    )

    audio_value = st.audio_input(
        "무엇을 도와드릴까요?"
    )

    st.divider()

    # 이메일 발송 옵션
    email_requested = st.checkbox(
        "📧 이메일 발송 기능 사용"
    )

    recipient_email = st.text_input(
        "받는 사람 이메일 주소",
        placeholder="example@gmail.com",
        disabled=not email_requested
    )

    submit = st.form_submit_button("실행")

# 버튼을 눌렀을 때만 실행
if submit:
    # 업로드 된 파일이 있으면 디코딩
    text = ""
    if uploaded_file is not None:
        text = uploaded_file.read().decode("utf-8")

    # 녹음이 없으면 녹음 요청
    if audio_value is None:
        st.warning("음성을 녹음해주세요.")
        st.stop()

    # 시스템 메세지
    system_content = sys_role
    if text:
        system_content += f"\n\n다음 내용을 참고하세요:\n{text}"
    input_messages = [{"role": "system", "content": system_content}]

    # STT: 음성 → 텍스트
    transcript = client.audio.transcriptions.create(
        model="whisper-1",
        file=("audio.wav", audio_value, "audio/wav"))
    
    # 음성 인식 결과 출력
    st.subheader("🎤 음성 인식 결과")

    st.info(transcript.text)

    # 사용자 메시지
    input_messages.append({"role": "user", "content": transcript.text})

# 버튼을 눌렀을 때만 실행
if submit:

    # 회의록 읽기
    text = ""
    if uploaded_file is not None:
        text = uploaded_file.read().decode("utf-8")

    # 녹음 확인
    if audio_value is None:
        st.warning("음성을 녹음해주세요.")
        st.stop()

    # 시스템 메시지
    system_content = sys_role

    if text:
        system_content += f"\n\n다음 내용을 참고하세요:\n{text}"

    input_messages = [
        {"role": "system", "content": system_content}
    ]

    # 음성 인식(STT)
    transcript = client.audio.transcriptions.create(
        model="whisper-1",
        file=("audio.wav", audio_value, "audio/wav")
    )

    st.subheader("🎤 음성 인식 결과")
    st.info(transcript.text)

    input_messages.append({
        "role": "user",
        "content": transcript.text
    })

    # 여기부터 기존 코드도 if submit 내부에 있어야 함
    st.session_state.pending_email = None

    # 이메일 옵션 검증
    if email_requested:
        if not re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            recipient_email.strip()
        ):
            st.error("올바른 이메일 주소를 입력해주세요.")
            st.stop()

    # LLM 호출
    with st.spinner("답변을 준비하고 있습니다..."):

        if email_requested:
            input_messages[0]["content"] += f"""

[이메일 관련 규칙]
사용자가 음성으로 이메일 발송을 명시적으로 요청한 경우에만
send_email 도구를 호출하세요.
요청이 없다면 도구를 호출하지 마세요.
허용된 수신자 주소: {recipient_email.strip()}
실제 전송에는 추가 확인이 필요합니다.
"""

            response = client.responses.create(
                model="gpt-4o-mini",
                input=input_messages,
                tools=email_tools,
                tool_choice="auto"
            )

        else:
            response = client.responses.create(
                model="gpt-4o-mini",
                input=input_messages
            )

        # 도구 호출 여부 확인
        tool_calls = [
            item for item in response.output
            if item.type == "function_call"
            and item.name == "send_email"
        ]

        if tool_calls and email_requested:
            arguments = json.loads(
                tool_calls[0].arguments
            )

            st.session_state.pending_email = {
                "to": recipient_email.strip(),
                "subject": arguments["subject"],
                "body": arguments["body"]
            }

            st.info("이메일 초안이 작성되었습니다.")

        else:
            answer = response.output_text

            st.subheader("🤖 에이블의 답변")
            st.write(
                answer if answer
                else "처리 결과를 확인해주세요."
            )


# 중요: 이메일 발송 확인 영역은 if submit 바깥에 유지
if st.session_state.get("pending_email") is not None:
    # 기존 이메일 미리보기 및 발송 버튼 코드 유지
    pass
