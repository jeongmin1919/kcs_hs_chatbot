import streamlit as st
from google import genai
import time
from datetime import datetime

import os
from dotenv import load_dotenv
from utils import HSDataManager, extract_hs_codes, clean_text, classify_question
from utils import handle_web_search, handle_hs_classification_cases, handle_overseas_hs, get_hs_explanations, handle_hs_manual_with_parallel_search

# 환경 변수 로드 (.env 파일에서 API 키 등 설정값 로드)
load_dotenv()

# Gemini API 설정
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
client = genai.Client(api_key=GOOGLE_API_KEY)

# Streamlit 페이지 설정
st.set_page_config(
    page_title="HS 품목분류 챗봇",  # 브라우저 탭 제목
    page_icon="📊",  # 브라우저 탭 아이콘
    layout="wide"  # 페이지 레이아웃을 넓게 설정
)

# 사용자 정의 CSS 스타일 추가
st.markdown("""
<style>
.main > div {
    display: flex;
    flex-direction: column;
    height: 85vh;  # 메인 컨테이너 높이 설정
}
.main > div > div:last-child {
    margin-top: auto;  # 마지막 요소를 하단에 고정
}
.stTextInput input {
    border-radius: 10px;  # 입력창 모서리 둥글게
    padding: 8px 12px;
    font-size: 16px;
}
</style>
""", unsafe_allow_html=True)

# HS 데이터 매니저 초기화 (캐싱을 통해 성능 최적화)
@st.cache_resource
def get_hs_manager():
    return HSDataManager()

# 세션 상태 초기화
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []  # 채팅 기록 저장

if 'selected_category' not in st.session_state:
    st.session_state.selected_category = "AI자동분류"  # 기본값

if 'context' not in st.session_state:
    # 초기 컨텍스트 설정
    st.session_state.context = """당신은 HS 품목분류 전문가로서 관세청에서 오랜 경력을 가진 전문가입니다. 사용자가 물어보는 품목에 대해 아래 네 가지 유형 중 하나로 질문을 분류하여 답변해주세요.

질문 유형:
1. 웹 검색(Web Search): 물품개요, 용도, 기술개발, 무역동향 등 일반 정보 탐색이 필요한 경우.
2. HS 분류 검색(HS Classification Search): HS 코드, 품목분류, 관세, 세율 등 HS 코드 관련 정보가 필요한 경우.
3. HS 해설서 분석(HS Manual Analysis): HS 해설서 본문 심층 분석이 필요한 경우.
4. 해외 HS 분류(Overseas HS Classification): 해외(미국/EU) HS 분류 사례가 필요한 경우.

중요 지침:
1. 사용자가 질문하는 물품에 대해 관련어, 유사품목, 대체품목도 함께 고려하여 가장 적합한 HS 코드를 찾아주세요.
2. 품목의 성분, 용도, 가공상태 등을 고려하여 상세히 설명해주세요.
3. 사용자가 특정 HS code를 언급하며 질문하는 경우, 답변에 해당 HS code 해설서 분석 내용을 포함하여 답변해주세요.
4. 관련 규정이나 판례가 있다면 함께 제시해주세요.
5. 답변은 간결하면서도 전문적으로 제공해주세요.

지금까지의 대화:
"""

class RealTimeProcessLogger:
    def __init__(self, container):
        self.container = container
        self.log_placeholder = container.empty()
        self.logs = []
        self.start_time = time.time()
    
    def log_actual(self, level, message, data=None):
        """실제 진행 상황만 기록"""
        elapsed = time.time() - self.start_time
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        log_entry = {
            "time": timestamp,
            "elapsed": f"{elapsed:.2f}s",
            "level": level,
            "message": message,
            "data": data
        }
        self.logs.append(log_entry)
        self.update_display()
    
    def update_display(self):
        log_text = ""
        icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "DATA": "📊", "AI": "🤖", "SEARCH": "🔍"}
        
        for log in self.logs[-8:]:
            icon = icons.get(log['level'], "📝")
            data_str = f" | {log['data']}" if log['data'] else ""
            log_text += f"`{log['time']}` `+{log['elapsed']}` {icon} {log['message']}{data_str}\n\n"
        
        self.log_placeholder.markdown(log_text)
    
    def clear(self):
        self.logs = []
        self.log_placeholder.empty()


def process_query_with_real_logging(user_input):
    """실제 진행사항을 기록하면서 쿼리 처리"""
    
    log_container = st.container()
    logger = RealTimeProcessLogger(log_container)
    
    try:
        logger.log_actual("INFO", "Query processing started", f"Input length: {len(user_input)}")
        
        start_time = time.time()
        hs_manager = get_hs_manager()
        load_time = time.time() - start_time
        logger.log_actual("SUCCESS", "HSDataManager loaded", f"{load_time:.2f}s")
        
        category = st.session_state.selected_category
        logger.log_actual("INFO", "Category selected", category)
        
        if category == "AI자동분류":
            logger.log_actual("AI", "Starting LLM question classification...")
            start_classify = time.time()
            q_type = classify_question(user_input)
            classify_time = time.time() - start_classify
            logger.log_actual("SUCCESS", "LLM classification completed", f"{q_type} in {classify_time:.2f}s")
        else:
            category_mapping = {
                "웹검색": "web_search",
                "국내HS분류사례 검색": "hs_classification", 
                "해외HS분류사례검색": "overseas_hs",
                "HS해설서분석": "hs_manual",
                "HS해설서원문검색": "hs_manual_raw"
            }
            q_type = category_mapping.get(category, "hs_classification")
            logger.log_actual("INFO", "Question type mapped", q_type)

        answer_start = time.time()
        
        if q_type == "web_search":
            logger.log_actual("SEARCH", "Initiating Google Search API call...")
            ai_start = time.time()
            answer = "\n\n +++ 웹검색 실시 +++\n\n" + handle_web_search(user_input, st.session_state.context, hs_manager)
            ai_time = time.time() - ai_start
            logger.log_actual("SUCCESS", "Web search completed", f"{ai_time:.2f}s, {len(answer)} chars")
            
        elif q_type == "hs_classification":
            logger.log_actual("AI", "Starting domestic HS classification search...")
            ai_start = time.time()
            answer = "\n\n +++ HS 분류사례 검색 실시 +++\n\n" + handle_hs_classification_cases(user_input, st.session_state.context, hs_manager)
            ai_time = time.time() - ai_start
            logger.log_actual("SUCCESS", "Domestic HS classification completed", f"{ai_time:.2f}s, {len(answer)} chars")
            
        elif q_type == "overseas_hs":
            logger.log_actual("AI", "Starting overseas HS classification search...")
            ai_start = time.time()
            answer = "\n\n +++ 해외 HS 분류 검색 실시 +++\n\n" + handle_overseas_hs(user_input, st.session_state.context, hs_manager)
            ai_time = time.time() - ai_start
            logger.log_actual("SUCCESS", "Overseas HS classification completed", f"{ai_time:.2f}s, {len(answer)} chars")
            
        elif q_type == "hs_manual":
            logger.log_actual("AI", "Starting enhanced parallel HS manual analysis...")
            ai_start = time.time()
            answer = "\n\n +++ HS 해설서 분석 실시 (병렬 검색) +++ \n\n" + handle_hs_manual_with_parallel_search(user_input, st.session_state.context, hs_manager, logger)
            ai_time = time.time() - ai_start
            logger.log_actual("SUCCESS", "Enhanced HS manual analysis completed", f"{ai_time:.2f}s, {len(answer)} chars")
            
        elif q_type == "hs_manual_raw":
            logger.log_actual("SEARCH", "Extracting HS codes...")
            hs_codes = extract_hs_codes(user_input)
            if hs_codes:
                logger.log_actual("SUCCESS", f"Found {len(hs_codes)} HS codes", ", ".join(hs_codes))
                logger.log_actual("DATA", "Retrieving raw HS explanations...")
                raw_start = time.time()
                raw_answer = clean_text(get_hs_explanations(hs_codes))
                raw_time = time.time() - raw_start
                answer = "\n\n +++ HS 해설서 원문 검색 실시 +++ \n\n" + raw_answer
                logger.log_actual("SUCCESS", "Raw HS manual retrieved", f"{raw_time:.2f}s, {len(raw_answer)} chars")
            else:
                logger.log_actual("ERROR", "No valid HS codes found in input")
                answer = "HS 코드를 찾을 수 없습니다. 4자리 HS 코드를 입력해주세요."

        answer_time = time.time() - answer_start
        logger.log_actual("SUCCESS", "Answer generation completed", f"{answer_time:.2f}s, {len(answer)} chars")
        
        total_time = time.time() - logger.start_time
        logger.log_actual("INFO", "Process completed successfully", f"Total time: {total_time:.2f}s")
        
        # Return the answer for external processing
        return answer
        
    except Exception as e:
        logger.log_actual("ERROR", f"Exception occurred: {str(e)}")
        logger.log_actual("ERROR", f"Error type: {type(e).__name__}")
        raise e


# 사이드바 설정 (main.py의 with st.sidebar: 부분 교체)
with st.sidebar:
    st.title("🚀 HS Chatbot")
    st.markdown("""
    ### 📊 HS 품목분류 전문 AI

    **🤖 AI 자동분류**
    - LLM 기반 질문 유형 자동 판별
    - 최적 검색 방식 자동 선택

    **🌐 웹 검색**  
    - Google Search API 실시간 정보
    - 시장동향, 뉴스, 산업현황

    **🇰🇷 국내 HS 분류검색**
    - 관세청 사례 1,000+ 데이터베이스
    - Multi-Agent 5그룹 병렬 분석
    - Head Agent 최종 취합

    **🌍 해외 HS 분류검색**
    - 미국/EU 관세청 데이터
    - 국제 분류 동향 비교 분석

    **📚 HS 해설서 분석** ⭐
    - **병렬 검색 시스템**
    - 관세율표 + 해설서 동시 검색
    - 가중치 기반 통합 (40% + 60%)
    - HIGH/MEDIUM 신뢰도 등급
    - 실시간 프로세스 로깅

    **📖 HS 해설서 원문**
    - 특정 HS코드 해설서 조회
    - 통칙/부/류/호 체계적 정리
    
    ---
    
    **💡 핵심 특징**
    - Multi-Agent 병렬 처리
    - 실시간 로깅으로 투명성 보장  
    - 듀얼 패스 검색으로 정확도 향상
    """)
    
    # 새로운 채팅 시작 버튼
    if st.button("새로운 채팅 시작하기", type="primary"):
        st.session_state.chat_history = []  # 채팅 기록 초기화
        # 컨텍스트 초기화 (기본 컨텍스트 재사용)
        st.session_state.context = """당신은 HS 품목분류 전문가로서 관세청에서 오랜 경력을 가진 전문가입니다. 사용자가 물어보는 품목에 대해 아래 네 가지 유형 중 하나로 질문을 분류하여 답변해주세요.

질문 유형:
1. 웹 검색(Web Search): 물품개요, 용도, 기술개발, 무역동향 등 일반 정보 탐색이 필요한 경우.
2. HS 분류 검색(HS Classification Search): HS 코드, 품목분류, 관세, 세율 등 HS 코드 관련 정보가 필요한 경우.
3. HS 해설서 분석(HS Manual Analysis): HS 해설서 본문 심층 분석이 필요한 경우.
4. 해외 HS 분류(Overseas HS Classification): 해외(미국/EU) HS 분류 사례가 필요한 경우.

중요 지침:
1. 사용자가 질문하는 물품에 대해 관련어, 유사품목, 대체품목도 함께 고려하여 가장 적합한 HS 코드를 찾아주세요.
2. 품목의 성분, 용도, 가공상태 등을 고려하여 상세히 설명해주세요.
3. 사용자가 특정 HS code를 언급하며 질문하는 경우, 답변에 해당 HS code 해설서 분석 내용을 포함하여 답변해주세요.
4. 관련 규정이나 판례가 있다면 함께 제시해주세요.
5. 답변은 간결하면서도 전문적으로 제공해주세요.

지금까지의 대화:
"""
        st.rerun()  # 페이지 새로고침

# 메인 페이지 설정
st.title("HS 품목분류 챗봇")
st.write("HS 품목분류에 대해 질문해주세요!")

# 질문 유형 선택 라디오 버튼
selected_category = st.radio(
    "질문 유형을 선택하세요:",
    ["AI자동분류", "웹검색", "국내HS분류사례 검색", "해외HS분류사례검색", "HS해설서분석", "HS해설서원문검색"],
    index=0,  # 기본값: AI자동분류
    horizontal=True,
    key="category_radio"
)
st.session_state.selected_category = selected_category

st.divider()  # 구분선 추가

# 채팅 기록 표시
for message in st.session_state.chat_history:
    if message["role"] == "user":
        st.markdown(f"""<div style='background-color: #e6f7ff; padding: 10px; border-radius: 10px; margin-bottom: 10px;'>
                   <strong>사용자:</strong> {message['content']}
                   </div>""", unsafe_allow_html=True)
    else:
        # HS 해설서 원문인지 확인
        if "+++ HS 해설서 원문 검색 실시 +++" in message['content']:
            # 마크다운으로 렌더링하여 구조화된 형태로 표시
            st.markdown("**품목분류 전문가:**")
            st.markdown(message['content'])
        else:
            st.markdown(f"""<div style='background-color: #f0f2f6; padding: 10px; border-radius: 10px; margin-bottom: 10px;'>
                    <strong>품목분류 전문가:</strong> {message['content']}
                    </div>""", unsafe_allow_html=True)


# 하단 입력 영역 (Form 기반 입력)
input_container = st.container()
st.markdown("<div style='flex: 1;'></div>", unsafe_allow_html=True)

with input_container:
    # Form을 사용하여 안정적인 입력 처리
    with st.form("query_form", clear_on_submit=True):
        user_input = st.text_input(
            "품목에 대해 질문하세요:", 
            placeholder="여기에 입력 후 Enter 또는 전송 버튼 클릭"
        )
        
        # 두 개의 컬럼으로 나누어 버튼을 오른쪽에 배치
        col1, col2 = st.columns([4, 1])
        with col2:
            submit_button = st.form_submit_button("전송", use_container_width=True)
        
        # 폼이 제출되고 입력값이 있을 때 처리
        if submit_button and user_input and user_input.strip():
            with st.expander("실시간 처리 과정 로그 보기", expanded=True):
                try:
                    # Process query with real-time logging
                    answer = process_query_with_real_logging(user_input)
                    
                    # Update chat history after successful processing
                    st.session_state.chat_history.append({"role": "user", "content": user_input})
                    st.session_state.chat_history.append({"role": "assistant", "content": answer})
                    st.session_state.context += f"\n사용자: {user_input}\n품목분류 전문가: {answer}\n"
                    
                    # Force rerun to display the new chat messages
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"처리 중 오류가 발생했습니다: {str(e)}")