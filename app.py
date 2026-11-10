import csv
import tempfile
from pathlib import Path

import streamlit as st
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, AIMessage

# 페이지 설정
st.set_page_config(page_title="FAQ 챗봇", page_icon="💬")
st.title("💬 EduVerse Academy FAQ 챗봇")


def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)


# GitHub의 FAQ CSV를 읽어, Streamlit 서버의 쓰기 가능한 위치에 벡터 DB 생성
@st.cache_resource
def get_vectorstore():
    csv_path = Path(__file__).resolve().parent / "data" / "eduverse_faq.csv"
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    docs = [
        Document(
            page_content=f"question: {row['question']}\nanswer: {row['answer']}",
            metadata={
                key: row[key]
                for key in ("category", "user_type", "plan", "channel")
            },
        )
        for row in rows
    ]
    if not docs:
        raise ValueError("FAQ CSV에 데이터가 없습니다.")

    embedding = OpenAIEmbeddings(model="text-embedding-3-small")
    db_dir = tempfile.mkdtemp(prefix="eduverse_faq_")
    vectorstore = Chroma(
        collection_name="eduverse_faq",
        embedding_function=embedding,
        persist_directory=db_dir,
    )
    vectorstore.add_documents(docs)
    return vectorstore


@st.cache_resource
def get_options():
    metas = get_vectorstore().get(include=["metadatas"])["metadatas"]
    keys = ["category", "user_type", "plan", "channel"]
    return {k: sorted({m[k] for m in metas if m and m.get(k)}) for k in keys}


@st.cache_resource
def get_chain():
    s_msg = """
    1. 반드시 제공된 문서 내용(context)에 근거하여 답변하세요.
    2. 문서에 없는 내용은 추측하지 말고 "업로드된 문서에서 확인되지 않습니다."라고 답하세요.
    3. 답변은 간결하고 명확하게 작성하세요.
    [문서]
    {context}"""
    prompt = ChatPromptTemplate.from_messages(
        [("system", s_msg), ("human", "{input}")]
    )
    llm = ChatOpenAI(model="gpt-4o-mini", streaming=True, temperature=0)
    return prompt | llm | StrOutputParser()


vectorstore = get_vectorstore()
options = get_options()
chain = get_chain()

# 사이드바 메타데이터 필터
with st.sidebar:
    st.header("🔎 검색 필터")
    categories = st.multiselect(
        "카테고리", options["category"], placeholder="전체"
    )
    user_type = st.selectbox("사용자 유형", ["전체"] + options["user_type"])
    plan = st.selectbox(
        "요금제", ["전체"] + [p for p in options["plan"] if p != "All"]
    )
    channel = st.selectbox(
        "접속 채널", ["전체"] + [c for c in options["channel"] if c != "All"]
    )
    k = st.slider("검색 문서 수(k)", 1, 10, 4)


def build_filter():
    conditions = []
    if categories:
        conditions.append({"category": {"$in": categories}})
    if user_type != "전체":
        conditions.append({"user_type": user_type})
    if plan != "전체":
        conditions.append({"plan": {"$in": [plan, "All"]}})
    if channel != "전체":
        conditions.append({"channel": {"$in": [channel, "All"]}})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    role = "user" if isinstance(message, HumanMessage) else "assistant"
    with st.chat_message(role):
        st.markdown(message.content)

user_input = st.chat_input("메시지를 입력하세요.")
if user_input:
    st.chat_message("user").markdown(user_input)
    docs = vectorstore.similarity_search(
        user_input, k=k, filter=build_filter()
    )

    with st.chat_message("assistant"):
        response_stream = chain.stream(
            {"context": format_docs(docs), "input": user_input}
        )
        full_response = st.write_stream(response_stream)

        with st.expander(f"참고한 FAQ ({len(docs)}건)"):
            for doc in docs:
                m = doc.metadata
                st.markdown(
                    f"**[{m.get('category')} · {m.get('user_type')} · "
                    f"{m.get('plan')} · {m.get('channel')}]**"
                )
                st.text(doc.page_content)

    st.session_state.messages.append(HumanMessage(content=user_input))
    st.session_state.messages.append(AIMessage(content=full_response))
