# Supabase 영구저장 설정

아래 설정을 하면 PC가 꺼져도 데이터가 유지됩니다.

## 1) Supabase 프로젝트 생성
- Supabase에서 새 프로젝트를 만듭니다.

## 2) 테이블 생성
SQL Editor에서 아래를 실행합니다.

```sql
create table if not exists public.study_app_state (
  id bigint primary key,
  data jsonb not null,
  updated_at timestamptz
);
```

## 3) Render 환경변수 등록
Render 서비스의 Environment에 아래 값을 추가합니다.

- `SUPABASE_URL` = `https://<project-ref>.supabase.co`
- `SUPABASE_SERVICE_ROLE_KEY` = Supabase `service_role` 키
- `SUPABASE_TABLE` = `study_app_state`

## 4) 재배포
- 저장 후 재배포하면 자동으로 Supabase를 사용합니다.
- 환경변수가 없거나 연결 실패 시에는 로컬 파일 방식으로 동작합니다.
