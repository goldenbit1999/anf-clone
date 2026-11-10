# dashboard 설계 (FR-09)

사용자 확인: 2026-11-09 (API 연결 = Vite 프록시, 갱신 = 목록 GET 폴링, 범위 = 읽기 전용, 수락 기준 AC-01~09).

## 1. 범위

**만드는 것.** `frontend/`에 읽기 전용 대시보드를 둔다. 구독 하나의 NetApp 계정 → 용량 풀 → 볼륨 → 스냅샷을 트리로 보여 주고, 행마다 `provisioningState`를 배지로 표시한다. 2초마다 다시 읽어서, 생성·삭제·되돌리기 중인 리소스의 상태가 새로 고침 없이 바뀐다.

행에 보이는 것:

| 종류 | 보이는 속성 |
| --- | --- |
| 계정 | 이름, 리소스 그룹, 위치, 상태 |
| 용량 풀 | 이름, 상태, `size`(TiB), `serviceLevel`, `qosType`, `utilizedThroughputMibps` / `totalThroughputMibps` |
| 볼륨 | 이름, 상태, 마운트 경로 `<mountTargets[0].ipAddress>:/<creationToken>`(있을 때), `protocolTypes`, `usageThreshold`(GiB), `actualThroughputMibps` |
| 스냅샷 | 이름, 상태, `created` |

**만들지 않는 것.**

- 생성·수정·삭제 UI. 요청은 curl이나 스크립트로 보내고 대시보드는 결과를 본다. ANF 포털 재현은 비목표다 (PRD §4).
- 메트릭 차트. FR-12에서 Prometheus 쿼리 API로 더한다 (D-08).
- `Failed` 리소스의 오류 코드·메시지. 리소스 본문에는 오류가 없고, 오류가 있는 작업 상태 URL은 요청을 보낸 쪽만 안다. 보이려면 anf-api에 ANF에 없는 읽기 엔드포인트를 더해야 해서 뺐다. `Failed` 배지만 보인다.
- Microsoft 로고와 자산.

## 2. 관련 ID

- PRD: FR-09, FR-11(frontend 작업), NFR-07(로컬 전용), §8 표(조사 생략, 검증은 브라우저 관찰과 타입 검사·빌드)
- ADR: D-02(React + TypeScript, Vite), D-13(인증 없음), §8 관측성("리소스는 anf-api에서"), §9.3 CI frontend 작업, §12 저장소 구조(`frontend/`)
- 스파이크: 없음. 데이터 플레인 동작에 기대는 설계가 없다.

## 3. 결정

| # | 결정 | 고른 것 | 버린 대안과 이유 |
| --- | --- | --- | --- |
| 1 | 브라우저가 anf-api를 부르는 길 | Vite dev·preview 서버의 프록시. 대시보드는 같은 출처의 `/subscriptions/...`를 부르고 Vite가 `ANF_API_URL`(기본 `http://127.0.0.1:8080`)로 넘긴다. FR-13 컨테이너에서는 웹 서버가 같은 프록시를 맡는다 | anf-api에 CORS: 대시보드만을 위한 동작을 API에 더하고 백엔드 제품 코드 해시가 바뀐다. anf-api가 빌드 결과를 제공: API와 UI가 한 프로세스에 묶인다 |
| 2 | 새로 고침 없는 갱신 | 목록 GET 폴링, 2초 간격. 앞 회가 끝난 뒤 2초를 기다리므로 요청이 겹치지 않는다 | SSE: ANF REST에 없는 API이고 백엔드가 바뀐다. 클론의 API에는 푸시가 없고, ARM LRO 계약도 클라이언트가 폴링하는 방식이다 |
| 3 | 범위 | 읽기 전용 | 생성·삭제 폼: 폼 검증과 오류 표시가 늘어 포털 재현에 가까워진다 |
| 4 | 구독 ID | 화면 입력란. 값은 URL `?subscription=`에 둔다(새로 고침·링크로 유지). 비어 있으면 안내만 보이고 요청하지 않는다 | 빌드 시점 환경 변수: 구독을 바꾸려면 다시 빌드해야 한다. 구독 목록 API: anf-api에 없다(구독은 ARM의 것) |
| 5 | 읽는 방법 | 회마다 트리 전체: 구독의 계정 목록 → 계정마다 풀 목록 → 풀마다 볼륨 목록 → 볼륨마다 스냅샷 목록. 같은 층은 병렬 | 펼친 가지만 읽기: 데모 규모(리소스 수십 개)에서는 필요 없다 |
| 6 | 읽기 실패 | 한 회의 어느 요청이든 실패하면 그 회를 버리고, 마지막으로 성공한 트리를 그대로 둔 채 오류 배너를 보인다. 폴링은 계속하고 다음 성공에서 배너가 사라진다 | 부분 트리 표시: 절반만 읽힌 트리는 리소스가 지워진 것처럼 보인다 |
| 7 | 삭제 중 사라진 부모 | 자식 목록이 `404`면(읽는 사이 부모가 지워짐) 실패가 아니라 빈 목록으로 본다 | 실패로 처리: 삭제 때마다 오류 배너가 깜박인다 |
| 8 | 테스트 도구 | Vitest + Testing Library(jsdom). 테스트를 먼저 쓴다. Python TDD 훅은 `.py`만 보므로 RED 확인은 절차로 지킨다 | Jest: Vite 설정을 따로 맞춰야 한다 |
| 9 | UI 라이브러리 | 없음. 손으로 쓴 CSS 한 파일 | 컴포넌트 라이브러리: 표 하나에 의존성이 과하다 |
| 10 | Node 위치 | Windows의 Node 22로 개발·빌드·실행한다(WSL에는 node가 없다). anf-api는 WSL에서 돌고 Windows에서 `127.0.0.1:8080`으로 닿는다(WSL2 localhost 전달). CI는 `ubuntu-24.04`, Node 22 | WSL에 Node 설치: 환경 준비가 하나 늘고 저장소가 `/mnt/c`라 `npm ci`가 느리다 (R-06) |

아직 정하지 않은 것: FR-13에서 대시보드를 무엇으로 제공할지(nginx 등)는 FR-13 설계에서 정한다.

## 4. API 계약

대시보드는 anf-api의 기존 GET만 쓴다. anf-api는 바뀌지 않는다. 모든 요청에 `?api-version=2026-08-01`을 붙인다.

| 요청 | 쓰는 응답 |
| --- | --- |
| `GET /subscriptions/{sub}/providers/Microsoft.NetApp/netAppAccounts` | `200` `{value: [...]}` |
| `GET {계정 id}/capacityPools` | `200` `{value}`, `404` → 빈 목록 |
| `GET {풀 id}/volumes` | `200` `{value}`, `404` → 빈 목록 |
| `GET {볼륨 id}/snapshots` | `200` `{value}`, `404` → 빈 목록 |

자식 목록의 URL은 부모 본문의 `id`에 붙여 만든다. 그 밖의 상태 코드와 네트워크 오류는 그 회의 실패다.

## 5. 상태 표시

대시보드는 상태를 만들지 않고 API의 `provisioningState` 문자열을 그대로 보인다. 배지 색만 나눈다.

| 값 | 배지 |
| --- | --- |
| `Succeeded` | 초록 |
| `Failed` | 빨강 |
| 그 밖(`Creating`, `Updating`, `Patching`, `Deleting`, `Reverting` 등) | 노랑(진행 중) |

삭제가 끝난 리소스는 다음 회의 목록에 없으므로 행이 사라진다.

## 6. 구조

```text
frontend/
├─ package.json          # scripts: dev, build, preview, typecheck, test
├─ vite.config.ts        # 프록시(dev·preview), 127.0.0.1 바인딩, Vitest 설정
├─ index.html
└─ src/
   ├─ armClient.ts       # fetchTree(subscriptionId): 목록 GET 4종 → 트리. 404 규칙
   ├─ useResourceTree.ts # 폴링 훅: 겹치지 않는 2초 주기, 마지막 성공 트리, 오류
   ├─ ResourceTree.tsx   # 트리 렌더링, 상태 배지, 속성 형식
   ├─ App.tsx            # 구독 입력(URL 동기화), 배너, 마지막 갱신 시각
   ├─ main.tsx, styles.css
   └─ *.test.ts(x)
```

명령 (`frontend/`에서): `npm ci`, `npm run dev`(127.0.0.1:5173), `npm run typecheck`(`tsc --noEmit`), `npm run build`, `npm test`(`vitest run`), `npm run preview`(127.0.0.1:4173).

CI: `.github/workflows/ci.yml`에 `frontend` 작업을 더한다 (`ubuntu-24.04`, Node 22, `npm ci` → typecheck → test → build).

## 7. 검증 기준

상태 반영 제한 시간: API의 상태가 바뀐 뒤 5초 이내에 화면에 보인다(폴링 2초 + 여유). 브라우저는 페이지를 한 번 연 뒤 다시 읽지 않는다.

| ID | 기준 |
| --- | --- |
| AC-01 | 트리가 API의 계정 > 풀 > 볼륨 > 스냅샷 계층, 이름, `provisioningState`와 일치한다 |
| AC-02 | 지연을 주입한 계정 생성(`ANF_FAULT_INJECTION` `netAppAccounts/create` `delaySeconds`)에서 행이 새로 고침 없이 `Creating`으로 나타났다가 `Succeeded`로 바뀐다 |
| AC-03 | 실제 데이터 플레인에서 볼륨과 스냅샷을 만들면 새로 고침 없이 나타나고, 볼륨이 `Succeeded`가 된 뒤 마운트 경로(`<IP>:/<creationToken>`)가 보인다. 그 경로가 API의 `mountTargets`와 같다 |
| AC-04 | 리소스를 삭제하면 `Deleting`이 보인 뒤 행이 사라진다 |
| AC-05 | 강제 실패를 주입한 작업의 리소스가 `Failed` 배지로 보인다 |
| AC-06 | anf-api를 멈추면 오류 배너가 뜨고 마지막 트리가 남는다. 다시 띄우면 새로 고침 없이 배너가 사라지고 트리가 갱신된다 |
| AC-07 | `npm run typecheck`, `npm run build`, `npm test`가 통과한다 |
| AC-08 | CI의 `frontend` 작업이 PR에서 통과한다 |
| AC-09 | 백엔드 제품 코드 내용 해시가 `f99bc5cf…`(FR-08 검증 값) 그대로이고 기존 pytest가 GREEN이다 |

AC-02·AC-04·AC-05는 결함 주입으로 진행 중 상태를 길게 만들어 관찰한다. AC-03만 root storage agent가 필요하다.

## 8. 구현 중 변경

- 코드 변경은 없다.
- 근거 정정 (5단계, 개념 문서 작성 중 지적): 처음 결정 1·2의 이유에 "CORS는 실제 ARM에 없는 동작", "ARM에는 푸시가 없다"고 썼는데, 조사를 생략한 FR이라 둘 다 확인한 사실이 아니다. 이유를 확인된 것(백엔드 무변경, ANF REST에 없는 API, LRO가 폴링 계약)으로 고쳤다. 결정 자체는 그대로다.
