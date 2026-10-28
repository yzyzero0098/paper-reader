[English](README.en.md) | **한국어**

# Paper Reader

논문 PDF를 열면 바로 AI 기능을 쓸 수 있는 **로컬 웹 리더**입니다. 번역, 그림 설명, 스마트 인용, 요약, 토론을 한 화면에서 하고, 모든 데이터는 내 컴퓨터에만 저장됩니다.

*A local web reader for research papers. English documentation: [README.en.md](README.en.md).*

## 기능

| 기능 | 동작 |
|---|---|
| 나란히 번역 | 원문 PDF는 왼쪽에 그대로, 오른쪽 패널에 **문장 단위 번역**이 표시되고 **함께 스크롤**됩니다. 번역 문장에 마우스를 올리면 원문의 해당 문장이, 원문에 올리면 번역 문장이 강조됩니다. 클릭하면 원문으로 이동합니다. |
| 덮어쓰기 번역 | 문단·제목·캡션 번역을 원문 위치 그대로 PDF 위에 덮어씌웁니다(레이아웃 유지). |
| 그림·표 설명 | 그림/표 위에 마우스를 올리면 `그림 설명` 버튼이 나타납니다. 이미지, 캡션, 해당 페이지 본문을 비전 모델에 보내 설명합니다. |
| 선택 · 우클릭 메뉴 | 드래그하면 설명 / 번역 / 수식 풀이 / 질문 / 형광펜 툴바가, 우클릭하면 같은 메뉴와 **질문 입력칸**이 뜹니다. |
| 스마트 인용 | 위첨자, `[12]`, `(3–5)`, 저자-연도 형식의 인용을 클릭하면 참고문헌 항목과 CrossRef 서지정보(DOI, 피인용수, 초록)가 뜨고, "왜 인용했는지"를 설명받을 수 있습니다. |
| 요약 · 토론 | 논문 전체를 구조화 요약하고, 논문 전문을 컨텍스트로 질문/토론합니다(쪽수 인용, 대화 저장). 모델과 추론 노력(빠르게·보통·깊게)을 고를 수 있습니다. |
| 노트 · 라이브러리 | 반투명 형광펜과 메모, PDF 업로드/삭제. 번역·요약은 캐시되어 다음부터 즉시 표시됩니다. |
| 토큰 사용량 | 상단 우측에 오늘/이 논문 토큰 합계, 올리면 작업별·모델별 내역이 보입니다. |

## 빠른 시작

요구 사항: **Python 3.11+**, **Node.js 18+**

```bash
git clone https://github.com/yzyzero0098/paper-reader.git
cd paper-reader
pip install -r backend/requirements.txt
```

| OS | 실행 |
|---|---|
| Windows | `start.bat` |
| macOS / Linux | `bash start.sh` |

처음 실행하면 프론트엔드를 자동으로 빌드하고 http://localhost:8000 이 열립니다. 이후 오른쪽 위 ⚙ 설정에서 AI를 연결하세요.

개발 모드(핫리로드): `dev.bat` (백엔드 8000 + Vite 5173).

## AI 연결

설정(⚙)에서 아래 중 하나 이상을 연결합니다. 작업별 기본 AI와 그림 설명용 비전 모델을 따로 고를 수 있습니다.

| 프로바이더 | 인증 | 비고 |
|---|---|---|
| **ChatGPT 계정** | 브라우저 로그인 (OpenAI *Sign in with ChatGPT*) | Plus/Pro **구독 사용량**으로 동작, API 키 불필요 |
| Claude (Anthropic) | API 키 | 비전 지원 |
| OpenAI (GPT) | API 키 | 비전 지원 |
| Google Gemini | API 키 | 비전 지원 |
| DeepSeek | API 키 | 텍스트 전용(그림 설명은 다른 비전 모델로 자동 전환) |
| OpenAI 호환 | Base URL (+키) | Ollama, LM Studio, OpenRouter 등 |

키는 `data/settings.json`에만 저장되며, 환경변수(`.env.example` 참고)가 있으면 자동으로 사용합니다.

### ChatGPT 계정 로그인 (구독 사용)

설정에서 "ChatGPT 계정으로 로그인"을 누르고 OpenAI 화면에서 앱 이름과 "ChatGPT 플랜 사용"에 동의하면 연결됩니다. 토큰은 `data/chatgpt_auth.json`에만 저장되고 1시간마다 자동 갱신됩니다(30일 이상 안 쓰면 재로그인). 앱별 사용 한도는 [ChatGPT 설정 → 사용량](https://chatgpt.com/settings/usage)에서 조정합니다.

- OpenAI의 해당 기능은 **로컬·오픈소스 앱용**이며 아직 프리뷰입니다. 이 프로젝트는 [공식 문서](https://developers.openai.com/siwc/token-sharing-open-source)의 로컬 앱 절차를 따릅니다. 서버에 올려 여러 사람이 쓰는 원격 호스팅은 별도 신청 대상이라 지원하지 않습니다.
- Claude Pro/Max 구독 토큰을 외부 앱에서 쓰는 것은 Anthropic 약관이 금지하고, Gemini 구독 연동은 공식 경로가 없어 넣지 않았습니다. 이 둘은 API 키로 사용하세요.

## Docker

```bash
docker compose up -d --build      # http://localhost:8000
```

- 데이터는 `paper-reader-data` 볼륨(`/data`)에 저장됩니다.
- 포트는 `127.0.0.1`에만 열립니다. 앱에 자체 로그인이 없으므로 **인터넷에 그대로 노출하지 마세요.**
- API 키는 셸 환경변수나 `.env` 파일(`.env.example` 참고)로 전달합니다.
- ChatGPT 로그인용 콜백 포트(1455)가 compose에 포함되어 있어 컨테이너에서도 로그인할 수 있습니다.

## 개인정보와 주의

- 논문 본문(요약·토론은 전문)은 **선택한 AI 프로바이더로 전송**됩니다. 공개하면 안 되는 원고는 로컬 모델(Ollama)이나 사내 허용된 프로바이더로만 쓰세요.
- 번역·요약·설명은 AI 출력이므로 틀릴 수 있습니다. 중요한 수치와 결론은 원문으로 확인하세요.
- 앱에 사용자 계정 기능이 없습니다. 한 컴퓨터에서 한 사람이 쓰는 용도로 설계했습니다.

## 구조

```
backend/app/
  main.py          FastAPI 라우트 (REST + SSE 스트리밍), 빌드된 프론트 정적 서빙
  pdf_engine.py    PyMuPDF: 텍스트 블록, 문장 위치, 그림/표 영역, 인용 마커, 참고문헌 위치
  citations.py     참고문헌 파싱 + CrossRef 조회
  services.py      번역·설명·요약·채팅 프롬프트, 캐시, 토큰 사용량 기록
  chatgpt_auth.py  Sign in with ChatGPT (PKCE, 루프백 콜백, 토큰 갱신·폐기)
  llm/             프로바이더 추상화 (chatgpt · anthropic · openai 호환 · gemini)
  config.py, db.py 설정(settings.json), SQLite(papers·cache·chats·highlights·usage)
backend/scripts/   레이아웃·인용 추출 점검용 개발 스크립트
frontend/src/      React + Vite (pages/Reader, components/PageView·SidePanel·SettingsModal)
data/              (자동 생성) papers/*.pdf, paper_reader.sqlite, settings.json, chatgpt_auth.json
```

## 알려진 한계

- 레이아웃 추출은 PyMuPDF 휴리스틱입니다. 스캔 PDF(이미지만 있는 경우)는 동작하지 않습니다.
- 복잡한 다중 패널 그림은 하나로 합쳐지거나 나뉠 수 있습니다.
- 덮어쓰기 모드는 번역문이 길면 글자가 작아집니다.
- 참고문헌 파싱은 번호형/저자-연도형을 지원하지만 특이한 형식은 일부 항목이 합쳐질 수 있습니다.

## 라이선스

[MIT](LICENSE)
