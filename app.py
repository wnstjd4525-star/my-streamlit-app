
import os
import streamlit as st
from openai import OpenAI

# OpenAI 클라이언트 생성
client = OpenAI()

# 페이지 설정
st.set_page_config(page_title="다국어 번역기", page_icon="🌍")
st.title("🌍 다국어 번역기")
st.write("원하는 문장을 선택한 언어로 자연스럽게 번역해 주는 서비스입니다.")

# 사용자 입력(텍스트)
korean_text = st.text_area(
    "번역할 한글 문장을 입력하세요.",
    height=150,
    placeholder="예: 인공지능은 우리의 일상과 업무 방식을 빠르게 변화시키고 있습니다."
)
language = st.selectbox("언어선택", ["영어", "일본어", "중국어", "불어", "독일어"], index=0)

# 번역 버튼
if st.button("번역하기"):

    if not korean_text.strip():
        st.warning("번역할 문장을 입력하세요.")
    else:
        with st.spinner("번역 중입니다..."):

            # 시스템 역할
            sys_role = f"""
            당신은 한국어를 {language}로 번역하는 전문 번역가입니다.
            원문의 의미와 뉘앙스를 자연스럽고 유창하게 살려 번역 결과만 간결하게 출력하세요.
            """

            # 프롬프트 구성
            prompt = f"""
            다음 문장을 {language}로 번역하세요.
            ---
            "{korean_text}"
            """

            # GPT 호출
            response = client.responses.create(
                model="gpt-4o-mini",
                input=[
                    {"role": "system", "content": sys_role},
                    {"role": "user", "content": prompt}
                ]
            )

            # 결과 출력
            translated_text = response.output_
