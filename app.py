"""에이블: 깔끔한 사이드바 메뉴 UI + 멀티모달 분석 + TTS."""
import io
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
from openai import OpenAI
from PIL import Image, UnidentifiedImageError

from config import get_setting, llm_model, stt_model, tts_model
from prompts.system_prompts import CHAT_INSTRUCTIONS
from services.meeting_service import analyze_meeting, build_meeting_report
from services.task_service import STATUSES, make_briefing, personal_tasks, rank_tasks, with_ids
from services.speech_service import transcribe_audio, make_speech
from services.email_service import send_email, valid_recipient

st.set_page_config(page_title='에이블 | AI 업무비서', page_icon='🤖', layout='wide', initial_sidebar_state='expanded')
ASSET_DIR = Path(__file__).resolve().parent / 'assets'
MAIN_IMAGE = ASSET_DIR / 'assistant_main.png'
SIDE_IMAGE = ASSET_DIR / 'assistant_side.png'

# 원본 화면 시안의 다크 모드, 간결한 여백, 둥근 모서리를 반영한 스타일
st.markdown("""<style>
[data-testid="stAppViewContainer"] {background: #090a0c;}
[data-testid="stSidebar"] {background: #0c0d10; border-right: 1px solid #24262b;}
.block-container {max-width: 1040px; padding-top: 1.35rem; padding-bottom: 3rem;}
[data-testid="stHeader"] {background: rgba(9,10,12,.86);}
h1, h2, h3 {letter-spacing: -0.045em;}
h1 {font-size: 1.72rem !important;}
h2, h3 {font-size: 1.26rem !important;}
[data-testid="stVerticalBlockBorderWrapper"] > div {border-radius: 14px;}
[data-testid="stFileUploader"] {border-radius: 12px;}
[data-testid="stMetric"] {background: #121417; border: 1px solid #26282c; border-radius: 12px; padding: .8rem 1rem;}
div.stButton > button[kind="primary"] {background: #12b8ae; color: #061313; border: 0;}
div.stButton > button {border-radius: 10px;}
[data-testid="stSidebar"] [role="radiogroup"] label {padding: .35rem .25rem;}
 </style>""", unsafe_allow_html=True)

DEFAULTS = {
    'analysis': None, 'tasks': [], 'messages': [], 'pending_email': None,
    'brief_audio': None, 'brief_audio_for': None, 'last_chat_audio': None,
    'last_transcript': '', 'last_chat_reply': '', 'owner': '김 대리',
    'auto_voice': False,
}
for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value.copy() if isinstance(value, (dict, list)) else value

api_key = get_setting('OPENAI_API_KEY')
if not api_key:
    st.error('OPENAI_API_KEY가 없습니다. Streamlit Community Cloud의 앱 Secrets를 확인하세요.')
    st.stop()

@st.cache_resource(show_spinner=False)
def get_client(key):
    return OpenAI(api_key=key, timeout=45.0, max_retries=1)

client = get_client(api_key)
today = datetime.now(ZoneInfo('Asia/Seoul')).date()


def reset_meeting():
    st.session_state.analysis = None
    st.session_state.tasks = []
    st.session_state.brief_audio = None
    st.session_state.brief_audio_for = None
    st.session_state.pending_email = None


def update_status(task_id):
    for task in st.session_state.tasks:
        if task['id'] == task_id:
            task['status'] = st.session_state[f'status_{task_id}']
            break
    st.session_state.brief_audio = None
    st.session_state.brief_audio_for = None


def format_problem(exc):
    name = type(exc).__name__
    if name in ('AuthenticationError', 'PermissionDeniedError'):
        return 'API 인증 또는 권한 오류입니다. 키와 프로젝트 권한을 확인하세요.'
    if name == 'RateLimitError':
        return '요청 한도 또는 API 사용량 제한입니다. 잠시 후 다시 시도하세요.'
    if name in ('APITimeoutError', 'APIConnectionError', 'TimeoutError'):
        return 'API 서버 연결이 지연되거나 실패했습니다.'
    if isinstance(exc, (ValueError, UnicodeError, json.JSONDecodeError)):
        return str(exc)[:220]
    return f'요청 처리 실패 ({name}). 앱 로그를 확인하세요.'


with st.sidebar:
    # 과도하게 큰 이미지를 피하고 로고/브랜드 영역만 간결하게 배치합니다.
    logo, name_col = st.columns([1, 3], vertical_alignment='center')
    with logo:
        if SIDE_IMAGE.is_file():
            st.image(str(SIDE_IMAGE), use_container_width=True)
        else:
            st.markdown('🤖')
    with name_col:
        st.markdown('**에이블**')
        st.caption('AI 개인비서 AIVLE')
    st.divider()
    page = st.radio(
        '메뉴',
        ['회의 통합 분석', '담당 업무', '업무 브리핑', 'AI 비서 대화'],
        format_func=lambda name: {
            '회의 통합 분석': '◈  회의 통합 분석',
            '담당 업무': '☷  담당 업무',
            '업무 브리핑': '▦  업무 브리핑',
            'AI 비서 대화': '◯  AI 비서 대화',
        }[name],
        label_visibility='collapsed',
        key='page_navigation',
    )
    st.divider()
    st.caption(f'미완료 업무 {sum(t.get("status") != "완료" for t in st.session_state.tasks)}건')
    with st.expander('⚙️ 설정', expanded=False):
        st.text_input('담당자 이름', key='owner', help='회의록의 담당자 표기와 같게 입력하세요.')
        st.caption(f'기준일 {today.isoformat()} · 한국 시간')
        st.toggle('AI 답변 자동 음성 생성', key='auto_voice', help='답변마다 TTS API를 호출하므로 비용이 추가됩니다.')
        st.caption(f'최근 대화 {len(st.session_state.messages) // 2}/10')
        st.caption('OpenAI: 설정됨' if api_key else 'OpenAI: 설정 필요')
        st.caption('Gmail: 설정됨' if get_setting('GMAIL_ADDRESS') and get_setting('GMAIL_APP_PASSWORD') else 'Gmail: 설정 필요')
        if st.button('새 대화 시작', use_container_width=True):
            st.session_state.messages = []
            st.session_state.last_transcript = ''
            st.session_state.last_chat_reply = ''
            st.session_state.last_chat_audio = None
            st.rerun()
        if st.button('회의/업무 데이터 초기화', use_container_width=True):
            reset_meeting()
            st.rerun()
    st.caption('대화·업무 데이터는 현재 세션에 보관됩니다.')

# 메인 영역은 선택된 페이지 하나만 표시합니다.
page_kicker = {
    '회의 통합 분석': 'AI 개인비서 AIVLE',
    '담당 업무': '업무 대시보드',
    '업무 브리핑': 'DAILY BRIEFING',
    'AI 비서 대화': 'AI ASSISTANT',
}
st.caption(page_kicker[page])
st.title(page)

if page == '회의 통합 분석':
    with st.container(border=True):
        st.markdown('**회의 자료 업로드**')
        c1, c2 = st.columns(2)
        with c1:
            text_file = st.file_uploader('회의록 TXT', type=['txt'], key='meeting_txt', help='UTF-8 텍스트 파일')
        with c2:
            image_file = st.file_uploader('화이트보드 이미지 (최대 8MB)', type=['png','jpg','jpeg'], key='meeting_img')
        # 화이트보드 미리보기는 제거했습니다. 파일명/형식 검증만 표시합니다.
        whiteboard_bytes, image_mime, image_error = None, None, None
        if image_file is not None:
            try:
                raw_bytes = image_file.getvalue()
                if not raw_bytes or len(raw_bytes) > 8_000_000:
                    raise ValueError('이미지는 8MB 이하의 PNG/JPG 파일이어야 합니다.')
                with Image.open(io.BytesIO(raw_bytes)) as img:
                    image_format = img.format
                    if image_format not in ('PNG', 'JPEG'):
                        raise ValueError('PNG 또는 JPG 이미지 파일만 지원합니다.')
                    img.verify()
                image_mime = 'image/png' if image_format == 'PNG' else 'image/jpeg'
                whiteboard_bytes = raw_bytes
                st.caption(f'✓ 화이트보드 업로드 완료: {image_file.name} · {len(raw_bytes) / 1024 / 1024:.1f}MB')
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                image_error = str(exc)
                st.error('이미지 검증 실패: ' + image_error)

        analyze_clicked = st.button('통합 분석 실행', type='primary', use_container_width=True)
    if analyze_clicked:
        if text_file is None or image_file is None:
            st.warning('회의록 TXT와 화이트보드 이미지를 모두 업로드해 주세요.')
        elif image_error or whiteboard_bytes is None:
            st.error('화이트보드 파일을 확인해 주세요.')
        elif text_file.size > 1_000_000:
            st.warning('회의록은 1MB 이하로 올려 주세요.')
        else:
            try:
                meeting_text = text_file.getvalue().decode('utf-8-sig')
                if not meeting_text.strip():
                    raise ValueError('회의록 내용이 비어 있습니다.')
                with st.spinner('두 자료를 통합 분석하고 담당 업무를 추출하는 중...'):
                    analysis = analyze_meeting(client, llm_model(), meeting_text, whiteboard_bytes, image_mime)
                reset_meeting()
                st.session_state.analysis = analysis
                st.session_state.tasks = with_ids(analysis.get('tasks', []))
                st.success(f'분석 완료 · 추출 업무 {len(st.session_state.tasks)}건')
            except Exception as exc:
                st.error(format_problem(exc))

    if st.session_state.analysis:
        info = st.session_state.analysis
        st.subheader(info.get('meeting_title', '통합 회의록'))
        st.write(info.get('summary', ''))
        a, b, c = st.columns(3)
        a.metric('추출 업무', len(st.session_state.tasks))
        b.metric('확정 결정', len(info.get('decisions', [])))
        c.metric('확인 필요', len(info.get('conflicts', [])))
        with st.expander('확정 결정사항', expanded=True):
            for item in info.get('decisions', []):
                st.markdown('- ' + item)
        with st.expander('검토 중인 사항'):
            for item in info.get('pending', []):
                st.markdown('- ' + item)
        with st.expander('자료 간 불일치 / 확인 필요'):
            for item in info.get('conflicts', []):
                st.warning(item)
        report = build_meeting_report(info, st.session_state.tasks)
        st.download_button('최종 회의록 다운로드 (.md)', report, 'final_meeting_report.md', mime='text/markdown')
        with st.expander('최종 회의록 텍스트 보기'):
            st.markdown(report)
    else:
        st.caption('자료를 업로드하고 분석을 실행하면 회의 요약과 추출된 업무가 표시됩니다.')

elif page == '담당 업무':
    if not st.session_state.analysis:
        st.info('먼저 회의 통합 분석 메뉴에서 자료를 분석해 주세요.')
    else:
        ranked = rank_tasks(st.session_state.tasks, today)
        mine = personal_tasks(ranked, st.session_state.owner)
        pending = [x for x in mine if x['status'] != '완료']
        m1, m2, m3 = st.columns(3)
        m1.metric('전체 업무', len(mine))
        m2.metric('미완료', len(pending))
        m3.metric('마감 임박/초과', len([x for x in pending if x['days_left'] is not None and x['days_left'] <= 2]))
        st.caption('우선순위 = 마감 긴급도 60점 + 중요도 25점 + 선행작업 15점 · AI 추정치는 확인 필요')
        show_all = st.checkbox('모든 담당자의 업무 표시')
        for task in (ranked if show_all else mine):
            with st.container(border=True):
                left, right = st.columns([3, 1], vertical_alignment='center')
                left.markdown('**' + task['title'] + '**')
                left.caption(f"담당 {task['owner']} · 마감 {task['due_date'] or '미정'} · {task['urgency_status']} · {task['priority_score']}점")
                status_key = f"status_{task['id']}"
                if status_key not in st.session_state:
                    st.session_state[status_key] = task.get('status', '미시작')
                right.selectbox('진행 상태', STATUSES, key=status_key, on_change=update_status, args=(task['id'],))
                with st.expander('업무 설명 및 출처'):
                    st.write(task.get('description', ''))
                    st.caption(task.get('source_notes', ''))
        if not (ranked if show_all else mine):
            st.warning('담당 업무를 찾지 못했습니다. 설정에서 담당자 이름을 확인해 주세요.')

elif page == '업무 브리핑':
    if not st.session_state.analysis:
        st.info('회의 분석 후 오늘의 업무 브리핑을 이용할 수 있습니다.')
    else:
        briefing = make_briefing(st.session_state.tasks, st.session_state.owner, today)
        with st.container(border=True):
            st.markdown(briefing)
        col1, col2 = st.columns(2)
        with col1:
            st.download_button('브리핑 다운로드', briefing, 'today_briefing.md', mime='text/markdown', use_container_width=True)
        with col2:
            listen = st.button('🔊 브리핑 음성 재생', use_container_width=True)
        if listen:
            try:
                with st.spinner('브리핑 음성 생성 중...'):
                    if st.session_state.brief_audio_for != briefing:
                        st.session_state.brief_audio = make_speech(client, tts_model(), briefing)
                        st.session_state.brief_audio_for = briefing
            except Exception as exc:
                st.error(format_problem(exc))
        if st.session_state.brief_audio is not None and st.session_state.brief_audio_for == briefing:
            st.audio(st.session_state.brief_audio, format='audio/mp3', autoplay=listen)

elif page == 'AI 비서 대화':
    st.caption('텍스트 또는 음성으로 질문하세요. 최근 10개 대화를 기억합니다.')
    if not st.session_state.messages:
        with st.container(border=True):
            if MAIN_IMAGE.is_file():
                st.image(str(MAIN_IMAGE), width=96)
            st.markdown('**이렇게 질문해 보세요**')
            st.caption('오늘 가장 급한 업무가 뭐야? · 회의에서 확정된 사항을 알려줘 · KPI 정의서를 어떻게 시작할까?')
    for message in st.session_state.messages[-20:]:
        with st.chat_message(message['role']):
            st.markdown(message['content'])
    audio_input = st.audio_input('음성으로 질문하기', key='chat_audio_input')
    voice_submit = st.button('녹음한 질문 실행', disabled=audio_input is None)
    user_question = st.chat_input('에이블에게 질문을 입력하세요...')
    if voice_submit and audio_input is not None:
        try:
            with st.spinner('음성 인식 중...'):
                user_question = transcribe_audio(client, stt_model(), audio_input.getvalue())
            st.session_state.last_transcript = user_question
            st.info('인식된 질문: ' + (user_question or '음성을 인식하지 못했습니다.'))
        except Exception as exc:
            st.error(format_problem(exc))
            user_question = None
    if user_question and user_question.strip():
        question = user_question.strip()
        if len(question) > 2500:
            st.warning('질문은 최대 2,500자까지 입력할 수 있습니다.')
        else:
            st.session_state.last_chat_audio = None
            email_intent = ('메일' in question or '이메일' in question) and any(w in question for w in ('보내', '전송', '공유'))
            if email_intent:
                if st.session_state.analysis:
                    report = build_meeting_report(st.session_state.analysis, st.session_state.tasks)
                    brief = make_briefing(st.session_state.tasks, st.session_state.owner, today)
                    kind = '오늘의 브리핑' if ('브리핑' in question or '오늘 할 일' in question) else '통합 회의록'
                    content = brief if kind == '오늘의 브리핑' else report
                    st.session_state.pending_email = {'to': '', 'subject': f'[에이블] {kind}', 'body': content}
                    answer = '이메일 초안을 준비했습니다. 아래 공유 영역에서 확인 후 전송할 수 있습니다.'
                else:
                    answer = '회의 분석을 먼저 진행한 후 이메일을 준비할 수 있습니다.'
            else:
                try:
                    context = ''
                    if st.session_state.analysis:
                        context = json.dumps({
                            'summary': st.session_state.analysis.get('summary'),
                            'decisions': st.session_state.analysis.get('decisions'),
                            'pending': st.session_state.analysis.get('pending'),
                            'conflicts': st.session_state.analysis.get('conflicts'),
                            'my_tasks': personal_tasks(rank_tasks(st.session_state.tasks, today), st.session_state.owner),
                        }, ensure_ascii=False)[:14000]
                    with st.spinner('답변 생성 중...'):
                        response = client.responses.create(
                            model=llm_model(),
                            instructions=CHAT_INSTRUCTIONS + f'\n사용자: {st.session_state.owner}\n오늘: {today}\n참고 업무 정보: {context}',
                            input=[*st.session_state.messages[-20:], {'role': 'user', 'content': question}],
                            max_output_tokens=1000,
                        )
                    answer = response.output_text.strip() or '응답이 비어 있습니다. 다시 질문해 주세요.'
                except Exception as exc:
                    answer = '답변 생성 실패: ' + format_problem(exc)
            st.session_state.messages.extend([{'role': 'user', 'content': question}, {'role': 'assistant', 'content': answer}])
            st.session_state.messages = st.session_state.messages[-20:]
            st.session_state.last_chat_reply = answer
            # 자동 TTS는 설정에서 사용자가 명시적으로 켠 경우에만 호출합니다.
            if st.session_state.auto_voice and not answer.startswith('답변 생성 실패:'):
                try:
                    with st.spinner('답변 음성 생성 중...'):
                        st.session_state.last_chat_audio = make_speech(client, tts_model(), answer)
                except Exception:
                    st.session_state.last_chat_audio = None
                    st.warning('텍스트 답변은 생성되었지만 음성을 만들지 못했습니다.')
            st.rerun()
    if st.session_state.last_chat_reply:
        with st.container(border=True):
            st.markdown('**🔊 에이블 답변 듣기**')
            play_reply = st.button('마지막 답변 음성으로 재생', use_container_width=True)
            if play_reply:
                try:
                    with st.spinner('답변을 음성으로 변환하는 중...'):
                        # 최근 답변에 대해 한 번만 생성해 중복 비용 방지
                        if st.session_state.last_chat_audio is None:
                            st.session_state.last_chat_audio = make_speech(client, tts_model(), st.session_state.last_chat_reply)
                except Exception as exc:
                    st.error(format_problem(exc))
            if st.session_state.last_chat_audio:
                st.audio(st.session_state.last_chat_audio, format='audio/mp3', autoplay=(play_reply or st.session_state.auto_voice))

# 이메일은 AI와 독립적으로 처리하며 반드시 사용자 최종 확인이 있어야 발송합니다.
st.divider()
with st.expander('✉️ 최종 회의록 / 업무 브리핑 이메일 공유', expanded=bool(st.session_state.pending_email)):
    if not st.session_state.analysis:
        st.info('회의 분석이 완료되면 이메일 공유가 활성화됩니다.')
    else:
        kind = st.radio('공유할 문서', ['최종 회의록', '오늘의 브리핑', '둘 다'], horizontal=True)
        if st.button('이메일 초안 작성'):
            report = build_meeting_report(st.session_state.analysis, st.session_state.tasks)
            brief = make_briefing(st.session_state.tasks, st.session_state.owner, today)
            content = {'최종 회의록': report, '오늘의 브리핑': brief, '둘 다': report + '\n\n---\n\n' + brief}[kind]
            st.session_state.pending_email = {'to': '', 'subject': f'[에이블] {kind}', 'body': content}
        if st.session_state.pending_email is not None:
            with st.form('email_confirm_form', clear_on_submit=False):
                to = st.text_input('받는 사람 이메일', value=st.session_state.pending_email.get('to', ''))
                subject = st.text_input('제목', value=st.session_state.pending_email.get('subject', ''))
                body = st.text_area('본문 (수정 가능)', value=st.session_state.pending_email.get('body', ''), height=220)
                confirm = st.form_submit_button('이메일 발송 확인', type='primary')
            if confirm:
                if not valid_recipient(to):
                    st.error('받는 사람 이메일 주소를 확인해 주세요.')
                elif not subject.strip() or not body.strip():
                    st.error('제목과 본문을 입력해 주세요.')
                else:
                    st.session_state.pending_email = {'to': to, 'subject': subject, 'body': body}
                    with st.spinner('Gmail 서버로 전송 중...'):
                        result = send_email(to, subject, body)
                    if result['status'] == 'success':
                        st.session_state.pending_email = None
                        st.success(result['message'])
                    else:
                        st.error(result['error'])
            if st.button('초안 취소'):
                st.session_state.pending_email = None
                st.rerun()
