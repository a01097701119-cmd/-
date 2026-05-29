# 5분 완성 가이드

## 지금 완성된 기능
- 날짜별 요약노트 업로드
- `.hwpx / .txt / .md` 업로드 자동 문제 생성
- 괄호채우기/단답형 랜덤 퀴즈
- 오답 위주 복습
- PC/핸드폰 공용 사용
- Supabase 연결 시 영구저장 (PC 꺼져도 유지)

## 1) GitHub에 업로드
- 현재 폴더 파일 전체를 GitHub 저장소에 올립니다.

## 2) Render 배포
- Render에서 `New +` -> `Blueprint`
- GitHub 저장소 연결
- 배포 완료 후 URL 발급

## 3) Supabase 영구저장 연결
- `SUPABASE_SETUP.md` 문서대로 테이블 생성
- Render Environment에 아래 3개 등록
  - `SUPABASE_URL`
  - `SUPABASE_SERVICE_ROLE_KEY`
  - `SUPABASE_TABLE=study_app_state`
- 재배포

## 4) 사용
- 발급 URL을 PC/핸드폰 브라우저에서 열기
- 날짜 선택 후 노트 업로드 -> 자동 문제 생성 -> 랜덤 퀴즈
