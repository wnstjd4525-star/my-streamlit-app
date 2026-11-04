
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
        file=("audio.wav", audio_value, "audio/wav"))

    # 사용자 메시지
    input_messages.append({"role": "user", "content": transcript.text})

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
