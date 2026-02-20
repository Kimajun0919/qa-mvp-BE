# OPS Automation (Health + Parity)

목표: 로컬/개발 환경에서 정기적으로 API 상태와 핵심 기능 동작을 자동 점검.

## 1) 수동 실행

### 빠른 점검 (회귀)
```bash
npm run ops:check
```

실행 내용:
1. 로컬 스택 정리/기동 (`scripts/ensure_local_stack.sh`)
2. Node/FastAPI health 확인
3. parity smoke (`scripts/smoke_parity.sh`)
4. analyze spot-check

결과 로그:
- `out/ops/ops_check_latest.log`

### 심층 점검 (실사이트)
```bash
TEST_URL=https://docs.openclaw.ai npm run ops:deep
```

실행 내용:
1. analyze (실사이트)
2. flow-map (siteProfile/score/risk)
3. structure-map (tree/roleGraph)
4. condition-matrix
5. checklist expansion

결과 로그:
- `out/ops/deep_check_latest.log`

## 2) 주기 실행 (macOS crontab 예시)

30분마다 점검:

```bash
crontab -e
```

추가:

```cron
*/30 * * * * cd /Users/kimhajun/.openclaw/workspace && /bin/bash -lc 'npm run ops:check' >> /Users/kimhajun/.openclaw/workspace/out/ops/cron.log 2>&1
```

## 3) 실패 시 점검 포인트

- `out/ops/ops_check_latest.log`
- `/tmp/qa_node_web.log`
- `/tmp/qa_fastapi.log`

자주 발생하는 이슈:
- 4173/8000 포트 점유
- 로컬 LLM 응답 지연(ollama)
- 네트워크 문제로 analyze 지연

## 4) 운영 권장

- 개발/실험: `LLM_PROVIDER=ollama`
- 안정 운영: `LLM_PROVIDER=openai`
- 테스트 URL은 기본 `https://example.com`에서 실제 대상 도메인으로 변경 가능:

```bash
TEST_URL=https://docs.openclaw.ai npm run ops:check
```
