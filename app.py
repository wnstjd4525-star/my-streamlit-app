
import os, base64, json, requests
import streamlit as st
from openai import OpenAI

# OpenAI 클라이언트 생성
client = OpenAI()

# 페이지 설정
st.set_page_config(page_title="음성 AI 서비스", page_icon="🤖", layout="wide")
st.title("음성 인식 AI 서비스")
st.write("음성으로 질문하시면 답변해 드립니다.")

# 역할 지정
sys_role = """
# AI 개인비서 '에이블' 역할 정의
sys_role = """
당신의 이름은 '에이블(AIVLE)'입니다.
당신은 KT AIVLE School 출신 김 대리의 전담 AI 개인비서입니다.

[기본 역할]
1. 사용자를 항상 '김 대리님'이라고 부릅니다.
2. 모든 응답은 한국어로 친절하고 명확하게 작성합니다.
3. 사용자의 업무 효율을 높이는 것을 최우선 목표로 합니다.
4. 자신을 소개할 때는 '김 대리님의 AI 개인비서 에이블'이라고 소개합니다.

[주요 업무]
1. 사용자가 제공한 회의록을 분석하고 핵심 내용을 요약합니다.
2. 회의에서 결정된 사항과 주요 논의 내용을 정리합니다.
3. 김 대리에게 배정된 업무를 빠짐없이 추출합니다.
4. 각 업무의 담당자, 세부 내용, 마감 기한을 정리합니다.
5. 사용자의 업무 관련 질문에 정확하게 답변합니다.

[응답 원칙]
1. 회의록에 없는 정보는 임의로 만들어내지 않습니다.
2. 확실하지 않은 내용은 '확인되지 않았습니다'라고 답합니다.
3. 업무 지시사항과 단순 의견을 구분합니다.
4. 복잡한 내용은 항목별로 정리하여 이해하기 쉽게 설명합니다.
5. 사용자의 요청이 모호하면 필요한 정보를 질문합니다.

[이메일 발송 원칙]
사용자가 명시적으로 이메일 발송을 요청한 경우에만
이메일 발송 기능을 사용합니다.
"""
"""

# 상태 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []

# 지시 영역
with st.form("task_form"):
    uploaded_file = st.file_uploader("텍스트 파일 업로드", type=["txt"])
    audio_value = st.audio_input("무엇을 도와드릴까요?")
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
    file=("audio.wav", audio_value, "audio/wav")
)

# 추가 기능 2번: STT 인식 결과 화면 출력
st.info(f"🎤 음성 인식 결과: {transcript.text}")

# 사용자 메시지
input_messages.append({
    "role": "user",
    "content": transcript.text
})

    # LLM 호출 및 응답 듣기
    with st.spinner("답변을 준비하고 있습니다..."):
        # LLM 호출
        response = client.responses.create(
            model="gpt-4o-mini",
            input=input_messages
        )
        answer = response.output_text

        # 응답 출력
        st.subheader("AI 답변")
        st.write(answer)
