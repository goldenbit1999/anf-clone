# 대시보드 (FR-09, 리소스 트리)

> 대시보드는 "anf-api의 목록 GET 네 가지를 2초마다 다시 읽어, 계정 > 용량 풀 > 볼륨 > 스냅샷 트리와 각 리소스의 `provisioningState`를 새로 고침 없이 보여 주는 읽기 전용 화면"이다. 이 문서의 핵심은 네 가지다. (1) 폴링은 ARM 장기 실행 작업(LRO)과 같은 "클라이언트가 상태를 끌어온다" 모델이다. 대시보드는 요청을 보낸 쪽이 아니어서 작업 URL이 없으므로 리소스 목록을 폴링한다. (2) 폴링 훅은 `setTimeout` 연쇄라서 읽기가 겹치지 않는다. `useEffect`의 정리 함수와 `stopped` 플래그가 옛 구독의 늦은 응답을 버린다. (3) 한 회의 읽기는 전부 성공하거나 전부 버린다. 실패하면 마지막 트리를 그대로 두고 배너만 띄운다. (4) 한계가 분명하다. `Failed`의 이유는 보이지 못하고, 요청 수는 리소스 수에 비례해 늘고(N+1), 반영 지연은 2초 + 읽기 시간이며, 가려진 탭에서는 브라우저가 타이머를 늦춘다.

코드 인용 기준: 커밋 `5cb9d4b` (frontend 내용 해시 `61c3eb62…`, 백엔드 제품 코드 내용 해시 `f99bc5cf…`는 FR-08 검증 값 그대로). 검증 도구 `backend/tests/e2e/dashboard_watch.py`는 검증 회차에 더해져 `@d405646`으로 인용한다.

FR-09(대시보드, 리소스)를 다룬다. 이 기능은 ANF 데이터 플레인 기능이 아니라 엔지니어링 결과물이다. PRD §8에서 FR-09는 조사(1단계)를 생략하는 FR이다. ANF 포털 재현이 비목표(PRD §3)이기 때문이다. 그래서 조사 브리프가 없고 1, 2절은 "해당 없음"이다. 사실의 근거는 설계 기록(`_workspace/dashboard/02_main_design.md`), 검증 보고서(`_workspace/dashboard/04_verifier_report.md`), 진행 기록(`_workspace/dashboard/00_progress.md`), 그리고 실제 코드다. 폴링을 ARM LRO와 이어 설명하는 부분만 계정 문서(`docs/concepts/netapp-account.md` §1.3·§1.4)에서 옮겼고, 거기 붙은 근거 표시([문서], [녹화], [미확인])를 그대로 남겼다.

---

## 1. ANF에서는

해당 없음. ANF 포털이 리소스를 어떻게 보여 주고 갱신하는지는 조사하지 않았다.

다만 대시보드의 갱신 방식을 정할 때 기댄 ARM/ANF 사실이 있다. 모두 계정 문서에서 옮긴 것이다.

- **비동기 작업은 클라이언트가 폴링한다.** 비동기 작업은 응답에 추적 URL(`Azure-AsyncOperation` 또는 `Location`)을 주고, 클라이언트가 그 URL을 종결 상태까지 폴링한다 [문서]. `Azure-AsyncOperation` URL은 진행 중이든 끝났든 `200`이고, 상태는 본문의 `status`다. 종결 값은 `Succeeded`, `Failed`, `Canceled`뿐이고 그 밖의 값은 모두 "진행 중"이다 [문서].
- **ANF는 `Retry-After`를 보내지 않았다** [녹화]. 폴링 간격은 클라이언트가 정한다.
- **실패한 작업의 오류는 작업 상태에 있다.** `Failed`면 작업 상태 본문에 `error: {code, message}`가 필수다 [문서]. 실서비스의 실패한 작업 상태는 HTTP `200`에 `status: "Failed"`, 일반 `error.code`, 구체 코드는 `error.details[]`였다 [녹화]. 단, 비동기 PUT·PATCH·DELETE가 실패한 뒤 **리소스의** `provisioningState`가 `Failed`가 되는지는 확인하지 못했다 [미확인].
- **리소스 상태 변화를 클라이언트에게 밀어 주는(push) 수단이 Azure에 있는지는 조사하지 않았다** [미확인]. 설계 기록은 "ARM에는 푸시가 없다"를 이유로 들었지만, 이 문서는 그것을 사실로 쓰지 않는다. 면접에서는 "내 API가 따르는 계약에는 푸시가 없다"까지만 말한다.

## 2. ONTAP에서는

해당 없음. 대시보드는 컨트롤 플레인(anf-api)의 리소스 상태만 읽는다. storage agent(ONTAP REST 부분 집합)나 데이터 플레인을 직접 부르지 않는다.

---

## 3. 이 프로젝트에서는

### 3.1 구조

```
브라우저 (Windows Chrome)  http://127.0.0.1:5173 (npm run dev) / :4173 (npm run preview)
  App.tsx            구독 ID 입력(URL ?subscription=), 오류 배너, 마지막 갱신 시각
   └ useResourceTree.ts   폴링 훅: 읽기 끝 → 2초 대기 → 다음 읽기 (겹치지 않음), 마지막 성공 트리 유지
       └ armClient.ts     fetchTree: 목록 GET 4종 → 트리, 자식 목록 404 = 빈 목록
   └ ResourceTree.tsx     트리를 표 행으로, 상태 배지(초록/노랑/빨강), 속성 요약
          |  같은 출처 GET /subscriptions/...?api-version=2026-08-01
          v
Vite dev·preview 서버 (Windows Node 22)  프록시 /subscriptions → ANF_API_URL (기본 http://127.0.0.1:8080)
          |  WSL2 localhost 전달
          v
anf-api (WSL, uvicorn)  목록 GET 4종 → SQLite resources 테이블
          (storage agent·데이터 플레인과는 연결되지 않는다)
```

한 회의 읽기(round)는 이렇게 진행된다. 같은 층은 병렬, 층 사이는 순서대로다.

| 층 | 요청 | 개수 |
| --- | --- | --- |
| 1 | `GET /subscriptions/{sub}/providers/Microsoft.NetApp/netAppAccounts` | 1 |
| 2 | `GET {계정 id}/capacityPools` | 계정 수 A |
| 3 | `GET {풀 id}/volumes` | 풀 수 P |
| 4 | `GET {볼륨 id}/snapshots` | 볼륨 수 V |

스냅샷은 잎이라 요청을 더 만들지 않는다. 그래서 한 회의 요청 수는 `1 + A + P + V`다. 검증 환경(계정 2, 풀 2, 볼륨 2)에서는 한 회에 7개였다.

화면의 행은 설계 §1대로다.

| 종류 | 보이는 속성 |
| --- | --- |
| 계정 | 이름, 리소스 그룹, 위치, 상태 |
| 용량 풀 | 이름, 상태, `size`(TiB), `serviceLevel`, `qosType`, `utilizedThroughputMibps` / `totalThroughputMibps` |
| 볼륨 | 이름, 상태, 마운트 경로 `<mountTargets[0].ipAddress>:/<creationToken>`(있을 때), `protocolTypes`, `usageThreshold`(GiB), `actualThroughputMibps` |
| 스냅샷 | 이름, 상태, `created` |

### 3.2 Python 개발자를 위한 React·TypeScript 최소 개념

이 코드를 설명하는 데 필요한 것만 추렸다.

| React·TS | 뜻 | Python으로 비유하면 |
| --- | --- | --- |
| 컴포넌트 `function App()` | 화면을 다시 그릴(render) 때마다 호출되어 JSX(화면 조각)를 돌려주는 함수 | 상태를 받아 HTML을 돌려주는 템플릿 함수 |
| `useState(초기값)` | 렌더 사이에 유지되는 값과 그 setter. setter를 부르면 React가 다시 렌더한다 | 객체 속성 + "바뀌면 다시 그려라" |
| `useEffect(fn, [deps])` | 렌더가 끝난 뒤 부수 효과(타이머, 네트워크)를 실행한다. `deps` 값이 바뀔 때만 다시 실행한다 | — |
| 정리 함수(cleanup) | `fn`이 돌려주는 함수. React가 다음 effect 실행 직전과 컴포넌트가 사라질 때 부른다 | `with` 블록의 `__exit__`, `try/finally` |
| effect 안의 `let stopped` | effect가 실행될 때마다 새로 생기는 지역 변수. 안쪽 함수가 클로저로 잡는다 | 함수 안 지역 변수를 잡은 내부 함수 |
| `setTimeout(f, ms)` | ms 뒤에 `f`를 한 번 실행 | `loop.call_later(ms / 1000, f)` |
| `setInterval(f, ms)` | ms마다 `f`를 실행. `f`가 돌려준 promise가 끝났는지 기다리지 않는다 | 고정 주기 스케줄러 |
| `Promise.all([...])` | 모두 성공하면 결과 배열, 하나라도 실패하면 즉시 실패. 나머지는 취소되지 않고 계속 돈다 | `asyncio.gather(...)` (기본 `return_exceptions=False`) |
| `x as string[]` | 타입 단언. 실행 중 검사는 없다 | `typing.cast` |

### 3.3 코드 따라가기

#### (1) 트리 읽기 — `armClient.ts`

- **`list` (`armClient.ts:24-30`)**: 모든 URL에 `?api-version=2026-08-01`을 붙인다(`armClient.ts:25`, 상수는 `armClient.ts:3`). anf-api의 모든 목록 GET이 `check_api_version`을 하기 때문이다(`arm_app.py:198` 등). `missingIsEmpty`가 참이고 `404`면 빈 목록을 돌려준다(`armClient.ts:27`). 그 밖의 `2xx`가 아닌 응답은 `GET {url} returned {status}` 예외다(`armClient.ts:28`). 이 문구가 그대로 배너에 나온다.
- **`node` (`armClient.ts:32-36`)**: 깊이(depth)가 종류다. 깊이 3(스냅샷)이면 요청 없이 잎으로 끝낸다(`armClient.ts:33`). 아니면 `{부모 id}/{자식 컬렉션}`을 읽고(`armClient.ts:34`, 컬렉션 이름은 `CHILD_COLLECTIONS`, `armClient.ts:22`) 자식마다 재귀를 `Promise.all`로 병렬 실행한다(`armClient.ts:35`). 자식 URL은 부모 본문의 `id`에 붙여 만든다. 대시보드가 경로 규칙을 따로 알 필요가 없다.
- **`fetchTree` (`armClient.ts:39-46`)**: 구독의 계정 목록부터 읽는다. 구독 ID만 `encodeURIComponent`로 감싼다(`armClient.ts:41`). 사람이 입력한 값이기 때문이다. 계정 목록에는 `missingIsEmpty = false`를 준다(`armClient.ts:43`). `fetchFn` 매개변수(`armClient.ts:39`, 기본값은 브라우저 `fetch`)는 테스트가 가짜 fetch를 넣는 자리다.

**404 규칙이 왜 둘로 나뉘는가.** anf-api의 자식 목록은 부모가 없으면 `404`다. `list_pools`(`capacity_pools.py:250-257`), `list_volumes`(`volumes.py:484-492`), `list_snapshots`(`snapshots.py:148-153`)가 모두 부모를 먼저 찾고 없으면 `not_found`를 던진다. 한 회 안에서 계정 목록을 읽은 뒤 그 계정이 삭제를 끝내면, 다음 층의 풀 목록이 `404`가 된다. 이것은 실패가 아니라 "그 가지는 이제 없다"는 뜻이라 빈 목록으로 본다(설계 결정 7). 반면 구독 범위 계정 목록(`list_accounts`, `accounts.py:104-108`)은 부모 검사가 없어 어떤 구독 ID에도 `200`이다. 그러니 계정 목록의 `404`는 경로나 프록시가 잘못됐다는 뜻이고, 실패로 본다.

**전부 아니면 전무(all-or-nothing).** 어느 층의 어느 요청이든 예외를 던지면 `Promise.all`이 거부되고, 그 거부가 `fetchTree`까지 올라간다(`armClient.ts:35`, `armClient.ts:45`). 부분 트리는 만들지 않는다. 절반만 읽힌 트리는 리소스가 지워진 것처럼 보이기 때문이다(설계 결정 6).

#### (2) 폴링 훅 — `useResourceTree.ts`

전체가 50줄이다. 상태는 세 가지다(`ResourceTreeState`, `useResourceTree.ts:6-12`): `tree`(마지막으로 성공한 트리, 한 번도 성공 못 했으면 `null`), `error`(가장 최근 읽기가 실패했으면 그 메시지), `updatedAt`(마지막 성공 시각). 아래는 `useResourceTree.ts:24-47`의 effect다. 주석의 숫자가 원본 줄 번호이고, 정리 함수(원본 4줄)만 한 줄로 줄였다.

```ts
useEffect(() => {
  setState(EMPTY);                       // 25: 구독이 바뀌면 옛 트리를 바로 버린다
  if (!subscriptionId) return;           // 26: 구독이 없으면 요청하지 않는다
  let stopped = false;                   // 27: 이 effect 실행만의 플래그
  let timer: ReturnType<typeof setTimeout>;

  async function poll() {
    try {
      const tree = await fetchTree(subscriptionId);
      if (stopped) return;               // 33: 늦게 온 응답은 버린다. 다음 타이머도 걸지 않는다
      setState({ tree, error: null, updatedAt: new Date() });
    } catch (e) {
      if (stopped) return;               // 36
      setState((last) => ({ ...last, error: e instanceof Error ? e.message : String(e) }));
    }
    timer = setTimeout(poll, POLL_INTERVAL_MS);   // 39: 읽기가 끝난 뒤에야 다음 2초를 건다
  }

  poll();                                // 42
  return () => { stopped = true; clearTimeout(timer); };   // 43-46: 정리 함수
}, [subscriptionId]);                    // 47
```

**(a) effect의 수명.** 의존성 배열이 `[subscriptionId]`라서(`useResourceTree.ts:47`) effect는 구독 ID가 바뀔 때마다 한 번 새로 실행된다. 같은 구독에서 2초마다 다시 렌더되어도 effect는 다시 실행되지 않는다. 폴링 루프 하나가 구독 하나에 묶이는 구조다. 구독이 바뀌거나 컴포넌트가 사라지면 React가 먼저 옛 실행의 정리 함수를 부르고(`useResourceTree.ts:43-46`), 그다음 새 실행을 시작한다.

**(b) `stopped` 플래그가 하는 두 가지 일.** 정리 함수의 `clearTimeout(timer)`만으로는 부족하다. `clearTimeout`은 "예약된 다음 읽기"를 취소할 뿐, **이미 진행 중인 읽기**는 멈추지 못한다. 구독을 A에서 B로 바꾸는 순간 A의 읽기가 진행 중이었다고 하자.

```
effect#A 실행    stoppedA = false, poll(A) 시작 ─── fetch 진행 중 ──────────────────┐
사용자가 B 제출  cleanup#A: stoppedA = true, clearTimeout(timerA)  ← 아직 타이머 없음, 효과 없음
                effect#B 실행: setState(EMPTY), stoppedB = false, poll(B) 시작
poll(B) 끝      setState(B의 트리)                                                 │
poll(A) 늦게 끝 ─────────────────────────────────────────────────────────────────┘
                if (stoppedA) return  → B의 화면을 덮어쓰지 않고, setTimeout도 걸지 않는다
```

`stopped`가 없으면 두 가지가 깨진다.
1. A의 늦은 응답이 `setState`로 B의 화면을 A의 리소스로 덮는다. 사용자는 B 구독을 보고 있다고 믿는다.
2. A의 `poll`이 39번 줄까지 내려가 새 타이머를 건다. 정리 함수는 이미 지나갔으므로 이 타이머를 아무도 취소하지 못한다. A의 폴링 루프가 B와 나란히 영원히 돈다.

`stopped`는 effect 실행마다 새로 만드는 지역 변수이고(`useResourceTree.ts:27`), `poll`이 클로저로 잡는다. A의 정리 함수는 A의 `stopped`만 참으로 바꾸고 B의 것은 건드리지 않는다. 모듈 전역 변수였다면 B가 시작할 때 다시 거짓으로 돌려놓아 A의 늦은 응답을 막지 못했을 것이다. Python으로 말하면 작업마다 따로 만든 취소 토큰(`threading.Event`)을 그 작업의 함수에 넘기는 것과 같다.

이 동작은 `useResourceTree.test.tsx:82-96`이 그대로 시험한다. A의 읽기를 끝나지 않게 걸어 두고 B로 바꾼 뒤, A를 `Failed` 트리로 늦게 끝내도 화면은 B의 `Succeeded` 트리 그대로다. 컴포넌트가 사라질 때 폴링이 멈추는 것은 `useResourceTree.test.tsx:98-105`가 본다(unmount 뒤 10초 동안 추가 호출 0).

참고로 `main.tsx:7`은 앱을 `StrictMode`로 감싼다. React는 개발 모드에서 effect를 "실행 → 정리 → 다시 실행"으로 한 번 더 돌려 정리 함수가 빠진 코드를 드러낸다고 문서화되어 있다. 이 코드에서는 첫 실행의 읽기가 `stopped`로 버려진다. 이번 검증은 프로덕션 빌드(`npm run preview`)로 했으므로 이 동작은 관찰하지 않았다.

**(c) `setTimeout` 연쇄가 `setInterval`보다 나은 이유.** 다음 읽기는 이번 읽기가 성공하든 실패하든 **끝난 뒤에** 예약된다(`useResourceTree.ts:39`). `setInterval(poll, 2000)`은 `poll`이 돌려준 promise를 기다리지 않고 2초마다 새로 부른다. 한 회가 3초 걸리면 이렇게 된다.

```
setInterval(poll, 2000), 한 회가 3초 걸릴 때
 0s  읽기#1 ━━━━━━━━━━━━┫3s
 2s           읽기#2 ━━━━━━━━━━━━┫5s
 4s                    읽기#3 ━━━━━━━━━━━━┫7s     ← 늘 2~3회가 동시에 진행 중

setTimeout 연쇄 (이 코드)
 0s  읽기#1 ━━━━━━━━━━━━┫3s ··2초·· 5s 읽기#2 ━━━━━━━━━━━━┫8s ··2초·· 10s 읽기#3
```

겹치면 생기는 문제는 셋이다.
1. 응답 순서가 보장되지 않는다. 먼저 시작한 읽기가 늦게 끝나면 **더 오래된 트리가 더 새 트리를 덮어** 상태가 뒤로 갔다가 다시 앞으로 오는 깜박임이 생긴다.
2. API가 느려질수록 진행 중인 요청이 쌓인다. 서버가 힘들 때 부하가 오히려 늘어난다. 연쇄는 읽기 시간만큼 저절로 간격이 벌어진다.
3. 정리 함수가 여러 개의 진행 중 읽기를 상대해야 한다.

대가는 실제 주기가 "정확히 2초"가 아니라 "읽기 시간 + 2초"라는 점이다. 설계 §7의 반영 제한 5초가 "폴링 2초 + 여유"인 이유다. Python으로 쓰면 이 루프는 `while True: await read(); await asyncio.sleep(2)`이고, `setInterval`은 앞 작업이 끝났는지 보지 않는 고정 주기 스케줄러다.

대조로, 검증자의 화면 기록기는 `setInterval`로 100 ms마다 DOM을 읽었다(보고서 "관찰 방법"). DOM 읽기는 동기 작업이라 겹칠 수 없으니 그 경우에는 문제가 없다. 연쇄가 중요한 것은 **비동기** 작업을 주기적으로 할 때다.

이 성질은 `useResourceTree.test.tsx:43-56`이 가짜 시계로 시험한다. 첫 읽기를 10초 동안 끝나지 않게 두면 호출은 1번뿐이다. 끝낸 뒤 1,999 ms에는 여전히 1번이고 2,000 ms에 2번째가 나간다.

**(d) 실패하면 마지막 트리를 유지한다.** 성공하면 `{ tree, error: null, updatedAt: new Date() }`로 통째로 바꾼다(`useResourceTree.ts:34`). 실패하면 함수형 갱신 `setState((last) => ({ ...last, error }))`를 쓴다(`useResourceTree.ts:37`). `tree`와 `updatedAt`은 그대로 두고 `error`만 채운다. 그리고 폴링은 계속된다(`useResourceTree.ts:39`는 `try/catch` 밖에 있다).

여기서 함수형 갱신이 필수인 이유가 있다. effect는 구독마다 한 번만 실행되므로, effect 안에서 훅의 `state` 변수를 직접 쓰면 effect가 만들어질 때의 값, 즉 `EMPTY`를 잡는다(오래된 클로저, stale closure). `{ ...state, error }`로 썼다면 실패할 때마다 트리가 지워졌을 것이다. `last`는 React가 그 시점의 최신 상태를 넘겨준다.

`updatedAt`이 마지막 성공 시각에 멈춘다는 것도 의도된 신호다. 화면 아래 `Updated 6:24:52 PM`이 더 이상 바뀌지 않으면, 사람은 보고 있는 트리가 낡았다는 것을 안다. 다음 성공에서 `error: null`이 되어 배너가 사라진다. 이 흐름은 `useResourceTree.test.tsx:58-73`이 시험한다(성공 → 실패: 트리 유지 + 오류 → 성공: 오류 사라짐).

#### (3) 화면 — `ResourceTree.tsx`, `App.tsx`

- **종류와 속성 (`KINDS`, `ResourceTree.tsx:9-37`)**: 깊이로 종류를 고르고, API 값을 형식만 바꿔 보인다. 계정의 리소스 그룹은 `id`를 `/`로 잘라 5번째 조각이다(`ResourceTree.tsx:13`, `/subscriptions/{sub}/resourceGroups/{rg}/...`). 바이트 값은 TiB·GiB로 나눈다(`ResourceTree.tsx:3-4`, `:18`, `:29`).
- **마운트 경로 (`mountPath`, `ResourceTree.tsx:40-43`)**: `mountTargets`가 있을 때만 `<IP>:/<creationToken>`을 만든다. `mountTargets`는 볼륨 생성이 성공한 뒤에 생기므로, `Creating` 볼륨에는 경로가 없다. 검증에서 `vol-b`가 `Creating`일 때 화면에 경로가 없었고, 같은 순간 API 본문에도 `mountTargets`가 없었다(AC-03).
- **상태 배지 (`stateClass`, `ResourceTree.tsx:46-50`)**: 글자는 API의 `provisioningState` 그대로이고 색만 나눈다. `Succeeded`는 `ok`(초록), `Failed`는 `failed`(빨강), 그 밖은 모두 `busy`(노랑)다. 진행 중 값을 목록으로 열거하지 않았으므로 `Reverting`처럼 새 값이 생겨도 노랑으로 맞게 보인다.
- **행 만들기 (`rows`, `ResourceTree.tsx:52-69`)**: 트리를 깊이 우선으로 펼쳐 표 행 배열로 만든다. 행마다 `key={resource.id}`(React가 행을 구별하는 키), `aria-level`(1~4, 검증 기록기와 테스트가 계층을 읽는 값), 깊이별 들여쓰기를 준다(`ResourceTree.tsx:57-59`). 풀·볼륨·스냅샷의 `name`은 `계정/풀/볼륨/스냅샷` 형식이라 마지막 조각만 보인다(`ResourceTree.tsx:59`). 빈 속성은 `filter(Boolean)`으로 뺀다(`ResourceTree.tsx:64`).
- **구독 입력 (`App.tsx:6-20`)**: 구독 ID는 URL `?subscription=`에 둔다. `useState(subscriptionFromUrl)`은 함수를 넘겨 첫 렌더에서 한 번만 URL을 읽는다(`App.tsx:11`). 입력란 값(`draft`, `App.tsx:12`)과 실제 구독(`subscriptionId`)을 나눠서, 타이핑하는 동안에는 읽지 않고 "Show"를 눌러야 구독이 바뀐다(`App.tsx:15-20`, 시험은 `App.test.tsx:52-60`). `history.replaceState`(`App.tsx:18`)라서 뒤로 가기 기록을 늘리지 않으면서 새로 고침·링크에는 남는다.
- **배너와 상태 문구 (`App.tsx:33-42`)**: `error`가 있으면 `role="alert"` 배너를 띄우고, 트리가 있을 때만 "Showing the last successful read."를 덧붙인다(`App.tsx:35`). "Loading…"은 트리도 오류도 없을 때만이라(`App.tsx:40`), 첫 읽기가 실패하면 로딩 대신 배너가 보인다(`App.test.tsx:77-84`).

#### (4) 프록시 — `vite.config.ts`

```ts
const proxy = { "/subscriptions": process.env.ANF_API_URL ?? "http://127.0.0.1:8080" };   // 6-8
server:  { host: "127.0.0.1", port: 5173, strictPort: true, proxy },                       // 12
preview: { host: "127.0.0.1", port: 4173, strictPort: true, proxy },                       // 13
```

페이지는 `http://127.0.0.1:4173`이고 anf-api는 `http://127.0.0.1:8080`이다. 포트가 다르면 출처(origin)가 다르므로, 브라우저가 페이지에서 anf-api 응답을 읽으려면 anf-api가 CORS 헤더를 보내야 한다. anf-api에는 CORS가 없다(진행 기록 0단계). 프록시를 쓰면 페이지는 자기 출처의 `/subscriptions/...`를 부르고, Vite 서버(Node)가 서버 대 서버로 anf-api에 넘긴다. 같은 `proxy` 객체를 dev와 preview가 함께 쓴다. 둘 다 `127.0.0.1`에만 바인딩한다(NFR-07 로컬 전용). `strictPort`는 포트가 차 있으면 다른 포트로 옮기지 않고 실패하게 한다.

부수 효과가 하나 있다. anf-api가 죽으면 브라우저는 네트워크 오류가 아니라 프록시의 **HTTP `502`**를 받는다. 검증 AC-06에서 anf-api 직접 호출은 연결 거부(`000`), 프록시 경유는 `502`였고, 배너 문구가 `... returned 502`였다. `armClient.ts:28`이 이것을 "그 회의 실패"로 처리했다.

`test: { environment: "jsdom", restoreMocks: true }`(`vite.config.ts:14`)는 Vitest 설정이다. jsdom은 Node 안의 가짜 DOM이라 브라우저 없이 컴포넌트를 렌더할 수 있다.

#### (5) 대시보드가 읽는 API — `backend/anf_api/arm_app.py`

대시보드는 anf-api의 기존 GET만 쓰고, anf-api는 바뀌지 않았다(백엔드 해시 `f99bc5cf…` 그대로, AC-09).

| 요청 | 라우트 |
| --- | --- |
| 구독의 계정 목록 | `list_accounts_in_subscription`, `arm_app.py:196-200` |
| 계정의 풀 목록 | `list_pools`, `arm_app.py:244-249` |
| 풀의 볼륨 목록 | `list_volumes`, `arm_app.py:307-312` |
| 볼륨의 스냅샷 목록 | `list_snapshots`, `arm_app.py:344-349` |

모두 `{"value": [...]}`를 돌려준다. 풀 본문의 `utilizedThroughputMibps`는 풀마다 볼륨 행을 다시 읽어 합한다(`pool_body`, `arm_app.py:118-120`). 그래서 풀 목록 요청 하나도 서버에서는 풀 수만큼 추가 조회를 한다.

`Failed`의 이유가 리소스 본문에 없는 것도 여기서 확인된다. 워커는 작업이 실패하면 리소스의 `provisioning_state`만 `Failed`로 바꾸고(UPDATE·PATCH면 이전 속성으로 되돌린 뒤), 오류는 작업 행에만 저장한다(`_finish`, `lro.py:137-149`). 오류 코드와 메시지는 작업 상태 본문에만 나온다(`operation_status_body`, `lro.py:164-165`). 그 URL은 요청을 보낸 클라이언트가 응답 헤더로 받은 것이다.

#### (6) 테스트 — 먼저 쓰고, 시간은 가짜 시계로

Vitest + Testing Library(jsdom)로 4개 파일 23개다. Python TDD 훅은 `.py`만 보므로, 모듈마다 테스트를 먼저 쓰고 RED를 확인하는 것은 절차로 지켰다(설계 결정 8, 진행 기록 3단계).

| 파일 | 시험하는 것 |
| --- | --- |
| `armClient.test.ts` (6개) | 목록 GET 4종으로 트리 구성, 빈 구독, 구독 ID 인코딩, 자식 404 = 빈 목록, 그 밖 상태는 전체 실패, 계정 목록 404는 실패 |
| `useResourceTree.test.tsx` (6개) | 즉시 읽고 2초마다 다시 읽음, 읽기 겹치지 않음, 실패 때 트리 유지와 복구, 구독 없으면 요청 없음, 구독 변경 때 늦은 응답 무시, unmount 때 정지 |
| `ResourceTree.test.tsx` (5개) | 계층과 `aria-level`, 배지 class, 종류별 속성, `mountTargets` 없으면 경로 없음, 빈 트리 문구 |
| `App.test.tsx` (6개) | 구독 없음 안내, URL에서 구독 읽기, 제출 때 URL 갱신, 로딩, 실패 배너 + 트리 유지, 첫 실패 때 배너 |

두 가지 기법을 설명할 수 있어야 한다.

- **가짜 fetch 표 (`fakeFetch`, `armClient.test.ts:16-22`)**: URL → `[상태, 본문]` 표로 답하고, 표에 없는 URL이 오면 예외를 던진다. 그래서 "필요 없는 요청을 더 보냈다"도 테스트 실패로 잡힌다.
- **가짜 시계 (`useResourceTree.test.tsx:14-24`)**: `vi.useFakeTimers()`로 `setTimeout`을 가짜로 바꾸고, `advance(ms)`가 `act` 안에서 `vi.advanceTimersByTimeAsync(ms)`를 불러 대기 중인 promise를 흘려보낸 뒤 시계를 돌린다. 덕분에 "1,999 ms에는 1번, 2,000 ms에 2번"(`useResourceTree.test.tsx:36-39`)처럼 밀리초 단위로 결정적인 시험이 된다. 실제 시간을 기다리지 않으므로 빠르고 흔들리지 않는다.

`App.test.tsx`는 훅을 통째로 가짜로 바꿔(`App.test.tsx:7-8`) 화면 분기만 본다. 훅 자체는 `useResourceTree.test.tsx`가, 네트워크 규칙은 `armClient.test.ts`가 맡는다. 층마다 아래층을 가짜로 바꾸는 구성이다.

#### (7) CI의 frontend 작업 — `.github/workflows/ci.yml:66-92`

- backend 작업과 나란히 도는 별도 작업이다(`needs` 없음). `ubuntu-24.04`, 제한 10분(`ci.yml:68-69`).
- `defaults.run.working-directory: frontend`(`ci.yml:70-72`)라서 모든 단계가 `frontend/`에서 돈다.
- `setup-node`에 Node 22와 `package-lock.json` 기준 npm 캐시(`ci.yml:76-80`). 개발 환경(Windows Node 22)과 같게 맞췄다(설계 결정 10).
- 단계는 `npm ci` → `npm run typecheck`(`tsc --noEmit`) → `npm test`(`vitest run`) → `npm run build`(`ci.yml:82-92`). 타입 검사를 빌드와 따로 두는 것은 Vite 빌드가 TypeScript를 변환만 하고 타입 오류로 실패하지 않기 때문이다. `ci.yml:66`의 주석대로 Python GREEN이 이 작업을 대신하지 않는다.
- PR #18의 Actions 실행 42741004014(`pull_request`)에서 Install·Type check·Test(4개 파일 통과)·Build가 모두 success였다(AC-08, 리더 확인).

### 3.4 왜 폴링인가 — ARM LRO와의 연결

계정 기능에서 만든 LRO 계층의 클라이언트 모델은 "클라이언트가 추적 URL을 종결 상태까지 폴링한다"이다 [문서](PRD G3, FR-01). ANF는 `Retry-After`를 보내지 않으므로 [녹화] 간격은 클라이언트가 정한다. 이 프로젝트의 e2e 클라이언트는 1초 간격, 30초 제한으로 폴링한다(계정 설계 결정 5).

대시보드도 같은 모델을 쓰지만, 끌어오는 대상이 다르다.

| | LRO 클라이언트 (curl, SDK, e2e) | 대시보드 |
| --- | --- | --- |
| 무엇을 보는가 | 자기가 보낸 작업 하나 | 구독의 모든 리소스 |
| 폴링 대상 | 응답 헤더의 작업 상태 URL | 목록 GET 4종 (리소스 본문의 `provisioningState`) |
| 알 수 있는 것 | 진행 상태, 실패하면 `error.code`·`message` | 리소스별 진행 상태. 실패 이유는 모른다 |
| 요청 수 | 작업당 1개 | 한 회에 `1 + A + P + V` |
| 간격 | 1초 | 읽기 끝난 뒤 2초 |

대시보드는 요청을 보낸 쪽이 아니라 옆에서 지켜보는 관찰자다. 그래서 작업 URL을 모르고, 리소스 자체를 다시 읽을 수밖에 없다. 리소스 본문에는 작업 계약에 따라 `provisioningState`가 들어 있으므로(FR-01) 진행 상태는 그것으로 충분하다.

푸시를 고르지 않은 이유는 설계 결정 2에 있다. SSE(Server-Sent Events)를 쓰려면 anf-api가 따르는 ANF REST 계약에 없는 엔드포인트를 더해야 하고, 백엔드 제품 코드가 바뀌어 해시가 달라진다. 해시가 바뀌면 이미 검증을 마친 기능들의 검증 대상 코드가 달라진다(`docs/concepts/ci.md` §3.4와 같은 논리).

2초는 ANF에서 온 값이 아니다. 설계 §7의 "상태가 바뀐 뒤 5초 안에 보인다"를 "폴링 2초 + 여유"로 나눈 값이다. LRO 클라이언트처럼 1초로 줄이면 한 회에 `1 + A + P + V`개인 요청이 두 배로 늘어난다.

### 3.5 설계 결정

| 결정 | 버린 대안 | 이유 |
| --- | --- | --- |
| 1. 브라우저 → anf-api는 Vite dev·preview 프록시. FR-13 컨테이너에서는 웹 서버가 같은 역할 | anf-api에 CORS. anf-api가 빌드 결과 제공 | CORS는 백엔드 제품 코드를 바꿔 해시가 달라진다. 빌드 결과 제공은 API와 UI를 한 프로세스에 묶는다 |
| 2. 목록 GET 폴링, 앞 회가 끝난 뒤 2초 | SSE | anf-api가 따르는 계약에 없는 API이고 백엔드가 바뀐다. 클라이언트가 폴링하는 LRO 모델과 같다 |
| 3. 읽기 전용 | 생성·삭제 폼 | 폼 검증과 오류 표시가 늘어 포털 재현에 가까워진다(PRD 비목표). 요청은 curl·스크립트로 보낸다 |
| 4. 구독 ID는 화면 입력란, 값은 URL `?subscription=`. 비어 있으면 요청하지 않음 | 빌드 시점 환경 변수. 구독 목록 API | 환경 변수는 구독을 바꾸려면 다시 빌드해야 한다. 구독 목록은 anf-api에 없다(구독은 ARM의 것) |
| 5. 회마다 트리 전체를 읽음. 같은 층은 병렬 | 펼친 가지만 읽기 | 데모 규모(리소스 수십 개)에서는 필요 없다 |
| 6. 한 요청이라도 실패하면 그 회를 버리고 마지막 성공 트리 + 배너. 폴링은 계속 | 부분 트리 표시 | 절반만 읽힌 트리는 리소스가 지워진 것처럼 보인다 |
| 7. 자식 목록 `404`는 빈 목록 | 실패로 처리 | 읽는 사이 부모가 지워진 것이다. 실패로 보면 삭제 때마다 배너가 깜박인다 |
| 8. Vitest + Testing Library(jsdom), 테스트 먼저 | Jest | Vite 설정을 그대로 쓴다. Jest는 따로 맞춰야 한다 |
| 9. UI 라이브러리 없음, CSS 한 파일(`styles.css`) | 컴포넌트 라이브러리 | 표 하나에 의존성이 과하다 |
| 10. Windows Node 22로 개발·빌드·실행, anf-api는 WSL(`127.0.0.1:8080`, WSL2 localhost 전달). CI도 Node 22 | WSL에 Node 설치 | 환경 준비가 하나 늘고, 저장소가 `/mnt/c`라 `npm ci`가 느리다 |
| (코드) 진행 중 상태를 열거하지 않고 `Succeeded`·`Failed` 밖은 모두 노랑 | 값마다 색 지정 | 대시보드는 상태를 만들지 않고 API 문자열을 그대로 보인다(설계 §5). 새 진행 중 값이 생겨도 맞게 보인다 |
| (코드) 실패 때 함수형 `setState` | `{ ...state, error }` | effect가 잡은 `state`는 첫 값(`EMPTY`)이라 트리가 지워진다 |

설계 §8 "구현 중 변경"은 "없음"이고, 코드를 읽어 확인한 결과도 설계와 같다.

### 3.6 한계

알고 쓰는 한계다. 면접에서 그대로 말할 수 있어야 한다.

1. **`Failed`의 이유를 보이지 못한다.** 오류 코드와 메시지는 작업 상태 본문에만 있고(`lro.py:164-165`), 리소스 본문에는 없다. 작업 상태 URL은 요청을 보낸 클라이언트만 응답 헤더로 받는다. 대시보드가 그것을 보이려면 "리소스의 최근 작업을 읽는" 엔드포인트처럼 ANF에 없는 API를 anf-api에 더해야 해서 뺐다(설계 §1). 검증 AC-05에서도 작업 상태에는 `"error":{"code":"InternalServerError","message":"Injected fault: capacityPools/patch (ANF_FAULT_INJECTION)."}`가 있었지만 화면은 `Failed` 배지뿐이었다. 대시보드가 언젠가 요청을 직접 보내게 되면(지금은 범위 밖) 자기가 받은 작업 URL을 폴링해 오류를 보일 수 있다.
2. **목록 GET N+1, 규모 한계.** 한 회의 요청 수는 `1 + A + P + V`이고, 층이 4개라 왕복 4번이 순서대로 일어난다. 검증 환경에서는 한 회 7개였다. 계산 예로, 계정 1, 풀 2, 볼륨 50이면 한 회 54개가 2초 + 읽기 시간마다 나간다. 볼륨이 수백 개면 수백 개다. 이 규모는 측정하지 않았다. 서버 쪽에서도 풀 목록 하나가 풀마다 볼륨을 다시 읽는다(`arm_app.py:118-120`). 설계는 데모 규모(리소스 수십 개)를 전제로 "펼친 가지만 읽기"를 버렸다(설계 결정 5).
3. **반영 지연은 2초 + 읽기 시간이고, 짧은 상태는 놓친다.** 폴링은 상태를 표본 추출(sampling)하는 것이지 전이를 모두 기록하는 것이 아니다. 검증에서 반영 지연 상한은 최대 4.2초였다(제한 5초, §5). 간격보다 짧은 상태는 화면에 아예 안 나올 수 있다. AC-05의 지연 없는 강제 실패에서 `Patching`은 약 10 ms(작업 `startTime` 02:23:14.390834Z → `endTime` 02:23:14.400987Z)라 화면과 0.5초 간격 API watcher 모두 보지 못했고 `Failed`만 보였다. 진행 중 상태와 `Failed`를 함께 보이려면 `{"delaySeconds": N, "fail": true}`를 주입하면 된다(보고서 참고 사항). 정확한 전이 시각이 필요하면 작업 상태의 `startTime`·`endTime`을 본다.
4. **가려진 탭에서는 브라우저가 타이머를 늦춘다.** 코드는 탭이 보이는지 확인하지 않고 계속 폴링한다. 검증 보고서는 탭이 `hidden`일 때 Chrome이 타이머를 1초 단위로 묶어 대시보드의 폴링과 기록기의 샘플이 함께 늦어지는 것을 관찰했다. 4초를 넘은 두 건(4.2초 둘)은 모두 `hidden` 구간이었다. 보고서는 창이 가려진 채 5분 넘게 두면 더 강한 타이머 제한이 걸릴 수 있다고 적었지만, 이번에 그런 구간은 관찰하지 않았다.
5. **실패한 회와 사라진 화면의 진행 중 요청은 취소하지 않는다(코드를 읽어 확인, 시험하지 않음).** `Promise.all`은 첫 실패에서 바로 거부되지만 나머지 요청은 계속 돈다(`asyncio.gather` 기본과 같다). 그 결과는 어디에도 쓰이지 않지만, 남은 요청이 2초보다 오래 걸리면 다음 회와 겹칠 수 있다. 그래서 "읽기가 겹치지 않는다"는 정확히는 "다음 회는 앞 회가 성공하거나 실패로 판정된 뒤에 시작한다"이다. 정리 함수도 `stopped`로 결과만 버리고 `fetch` 자체는 취소하지 않는다. `AbortController`로 요청을 취소하는 방법은 설계 기록에서 다루지 않았다.
6. **`Canceled`는 노랑(진행 중)으로 보인다.** ARM 작업 상태의 종결 값에는 `Canceled`도 있지만 [문서], 클론의 워커는 리소스를 `Succeeded`나 `Failed`로만 끝낸다(`lro.py:147`). 그래서 지금은 생기지 않는 경우다.
7. **잘못 친 구독 ID는 빈 구독처럼 보인다.** 클론의 계정 목록은 어떤 구독 ID에도 `200 {"value": []}`를 준다(`accounts.py:104-108`, 구독의 실제 구현은 PRD 비목표). 화면은 "No NetApp accounts in this subscription."이다.
8. **응답 모양을 실행 중에 검사하지 않는다.** `p.protocolTypes as string[]`(`ResourceTree.tsx:28`) 같은 타입 단언은 컴파일 때만 의미가 있다. API 필드 이름이 바뀌면 타입 검사는 통과하고 화면만 틀린다. 이번에는 검증자가 대시보드가 읽는 필드가 실제 응답에 같은 이름·대소문자로 있는지 확인했다(보고서 "통합 정합성").
9. **CI는 실제 브라우저를 띄우지 않는다.** CI는 jsdom 단위 테스트, 타입 검사, 빌드까지다. "새로 고침 없이 갱신된다"는 실제 브라우저 증거는 검증 회차(§5)에서만 나왔다.

---

## 4. 실제 ANF와 다른 점

ANF 포털과의 비교는 해당 없음이다(조사 생략, 포털 재현은 비목표). 대신 대시보드가 보여 주는 것이 실제 ANF에 대해 무엇을 말해 주고 무엇은 말해 주지 않는지를 적는다. 면접에서 "대시보드에 `Failed`가 떴으니 ANF도 그렇다"고 말하지 않기 위해서다.

| 항목 | 실제 ANF | 이 프로젝트 | 이유 |
| --- | --- | --- | --- |
| 화면 | ANF 포털. 조사하지 않음 | 읽기 전용 표 하나, Microsoft 자산 없음 | PRD §3 비목표 |
| 상태를 아는 방법 | 비동기 작업은 클라이언트가 추적 URL을 폴링 [문서]. `Retry-After` 없음 [녹화]. 리소스 변화를 밀어 주는 수단이 있는지는 조사하지 않음 [미확인] | 목록 GET을 읽기 끝난 뒤 2초마다 폴링 | 대시보드는 요청을 보낸 쪽이 아니라 작업 URL이 없다. 클론의 API에는 푸시가 없다 |
| 실패한 리소스 | 실패한 작업 상태는 `200` + `status: "Failed"` + `error`(구체 코드는 `error.details[]`) [녹화]. 비동기 실패 뒤 리소스가 `Failed`가 되는지는 [미확인] | 워커가 리소스를 `Failed`로 둔다(UPDATE·PATCH는 이전 속성으로 되돌림, `lro.py:144-147`). 오류는 작업에만 있고 화면은 배지만 | 대시보드는 클론의 상태를 그대로 비춘다. `Failed` 배지는 클론의 동작이지 ANF가 같다는 증거가 아니다 |
| 구독 | 구독은 ARM의 것이다(설계 결정 4) | 어떤 구독 ID에도 목록을 준다. 화면이 구독 ID를 입력받는다 | 구독의 실제 구현은 PRD 비목표 |
| 인증 | ARM이 토큰과 RBAC를 검사한 뒤 요청이 ANF RP에 닿는다(D-13) | 대시보드는 `Authorization`을 보내지 않는다. Vite와 anf-api 모두 `127.0.0.1`에만 바인딩 | D-13, NFR-07 |
| 브라우저 → API | 실제 ARM의 CORS 정책은 조사하지 않음 [미확인] | anf-api에 CORS 없음. Vite 프록시로 같은 출처 | 백엔드 제품 코드(해시)를 바꾸지 않는다. 설계 기록의 "CORS는 실제 ARM에 없는 동작"은 근거가 없어 이유로 쓰지 않는다 |

---

## 5. 검증

### 5.1 방법

검증은 real-env-verifier가 1회차(2026-11-09 18:12~18:29)에 실제 브라우저로 했다. 대상은 커밋 `5cb9d4b`이고, frontend·백엔드 해시가 시작과 끝에 모두 기준 값과 같았다. `npm run build` 결과를 `npm run preview`(`127.0.0.1:4173`)로 띄우고, WSL에서 storage agent(root)와 anf-api(결함 주입 포함)를 실제로 돌렸다.

- **브라우저**: Claude in Chrome, 탭 하나. 18:19:10에 `?subscription=…`으로 한 번 이동한 뒤 끝까지 이동·새로 고침을 하지 않았다.
- **"새로 고침 없음"의 증거**: 이동 직후 `window.__marker`에 값을 심었다. 새로 고침하면 사라지는 값이다. 판정마다 그 값이 남아 있는지, `performance.getEntriesByType("navigation")`이 `navigate` 하나뿐인지 확인했다. AC-06에서 중지 전 트리가 남아 있었다는 것도 증거다. 새로 고침했다면 첫 읽기가 실패해 트리 없이 배너만 보였을 것이다.
- **화면 기록기**: 같은 탭에서 100 ms마다 DOM(`tbody tr`의 `aria-level`과 칸 글자, 배지 class, 배너, `document.visibilityState`)을 읽어 바뀔 때만 `Date.now()`와 함께 쌓았다. DOM을 읽기만 하고 요청은 보내지 않는다.
- **API 기록기**: `dashboard_watch.py watch`(`backend/tests/e2e/dashboard_watch.py:94-110 @d405646`)가 Vite를 거치지 않고 anf-api를 직접 0.5초마다 읽어, 화면과 같은 행 형식이 바뀔 때마다 `t`(첫 관찰)와 `prev_t`(바로 앞 관찰)를 남겼다. 브라우저와 같은 Windows 시계를 쓴다. WSL 시계는 뒤로 갈 수 있기 때문이다(`dashboard_watch.py:4-5`).
- **반영 지연 상한** = 화면 첫 관찰 − API `prev_t`. API의 변화는 `prev_t`와 `t` 사이 어딘가에서 일어났으므로, `prev_t`를 빼면 실제 지연보다 크거나 같은 값(상한)이 된다.
- **독립 비교기**: `dashboard_watch.py compare`(`dashboard_watch.py:113-124 @d405646`)는 프론트엔드 코드를 쓰지 않고 목록 GET으로 트리를 다시 만들어 설계 §1의 속성 규칙을 따로 구현한 뒤 DOM 행과 비교한다. JavaScript가 `4.0`을 `"4"`로 찍는 숫자 형식까지 흉내 낸다(`_js`, `dashboard_watch.py:58-64 @d405646`).

### 5.2 결과

PASS 8 / FAIL 0 / UNVERIFIED 0 (AC-08은 리더가 GitHub Actions로 확인). 결함은 없었다.

| 기준 | 결과 | 근거 |
| --- | --- | --- |
| AC-01 트리가 API와 일치 | PASS | 계정 2, 풀 2, 볼륨 2(실제), 스냅샷 3, 빈 가지 2개. DOM 9행과 API 9행이 비교기에서 `identical=True` |
| AC-02 지연 주입 계정 생성 | PASS | `delaySeconds: 15`. 행이 `Creating`(노랑)으로 나타나고 `Succeeded`로 바뀜. 지연 상한 3.9 s / 0.6 s |
| AC-03 실제 볼륨·스냅샷 | PASS | `Succeeded` 뒤에만 경로 `172.30.0.129:/dash-vol-a`, `172.30.0.130:/dash-vol-b`. 이 경로로 `anf-nfs-client` 컨테이너가 NFSv3·NFSv4.1 마운트, 쓰기·읽기 성공. `.snapshot` 목록이 화면의 스냅샷 행과 같음 |
| AC-04 삭제 | PASS | 계정 `Deleting`(노랑) 뒤 행 사라짐. 실제 스냅샷·볼륨 삭제에서도 같음. 볼륨과 그 스냅샷 행이 함께 사라짐 |
| AC-05 강제 실패 | PASS | 풀 PATCH `fail: true`. 화면 `Failed`, 배지 class `state failed`(빨강). 지연 상한 1.3 s. 화면에 실패 이유는 없음(설계대로) |
| AC-06 anf-api 중지·재시작 | PASS | 중지 뒤 `... returned 502. Showing the last successful read. Retrying every 2 s.` 배너, 8행 유지, `Updated` 시각 멈춤. 같은 DB로 재시작하자 API 복구 1.3 s 뒤 배너 사라짐, 새 계정 행 1.0 s 뒤 나타남 |
| AC-07 typecheck·build·test | PASS | `tsc --noEmit` rc 0, `Tests 23 passed (23)` skip 없음, `vite build` rc 0 |
| AC-08 CI frontend 작업 | PASS | PR #18 실행 42741004014. Install·Type check·Test·Build success, backend 작업도 pass |
| AC-09 백엔드 불변 | PASS | 해시 `f99bc5cf…` 시작·끝 같음. Windows pytest `914 passed, 176 skipped`(skip은 live e2e·root 통합뿐) |

세션 전체(18:19~18:27)에서 오류 배너는 AC-06 중지 구간의 `502` 하나뿐이었다. 부모가 지워지는 동안 배너가 깜박이지 않았다.

### 5.3 측정값

반영 지연 상한, 표본 23개, 모두 5초 이하, 최대 4.2초. 보고서의 측정값 표를 탭 상태로 나누면 이렇다.

| 탭 상태 | 표본 | 최대 | 예 |
| --- | --- | --- | --- |
| visible | 9 | 2.6 s | `Failed` 1.3 s, 배너 사라짐 1.3 s, 새 계정 행 1.0 s, 계정 `Succeeded` 0.6 s |
| hidden | 14 | 4.2 s | 스냅샷 `snap-2` 행 4.2 s, `snap-b1` `Succeeded` 4.2 s, 계정 행 3.9 s |

`hidden`일 때는 기록기 자신도 같은 타이머 제한을 받아 화면 시각이 최대 1초 늦게 찍힌다. 그래서 `hidden` 값은 실제보다 보수적인 상한이다. 탭 가시성은 18:19~18:27 동안 22번 바뀌었다. 브라우저 도구가 탭을 다룰 때 `visible`, 약 20~40초 뒤 Windows 창이 가려져 `hidden`이 됐다.

### 5.4 증명하지 못한 것

- **규모.** 최대 9행이다. 요청 수와 읽기 시간이 리소스 수에 따라 어떻게 늘어나는지는 재지 않았다.
- **설계 결정 7의 경쟁 상태가 실제로 일어났는지.** 부모가 지워지는 동안 배너가 깜박이지 않았다는 것까지만 봤다. 그 사이 자식 목록 `404`가 실제로 왔는지는 기록하지 않았다. 규칙 자체는 `armClient.test.ts:54-61`이 시험한다.
- **dev 서버와 `StrictMode`.** 검증은 preview(프로덕션 빌드)로 했다. dev 서버의 프록시는 같은 `proxy` 객체를 쓰지만(`vite.config.ts:12-13`), 구현 중 손으로만 확인했다.
- **다른 브라우저, 5분 넘게 가려진 탭.** Windows Chrome 한 탭, 약 9분만 봤다.
- **진행 중 요청의 취소.** §3.6의 5번은 코드를 읽고 알게 된 성질이고 시험하지 않았다.

---

## 6. 개발 과정

1. **선행 확인.** 로드맵은 FR-10 다음에 FR-09를 두었지만 사용자가 FR-09를 먼저 지정했다. FR-09가 기대는 FR-02~FR-05가 모두 `done`이라 순서를 바꿔도 막히지 않았다. 지금 API가 주는 것을 확인했다. 목록 GET 4종은 있고, 모든 요청에 api-version이 필요하고, CORS 헤더와 구독 목록 엔드포인트는 없다. Node는 Windows에만 있었다.
2. **조사: 생략.** PRD §8에 따라 FR-09는 조사를 거치지 않는다.
3. **설계.** 사용자가 API 연결(Vite 프록시), 갱신(목록 GET 2초 폴링), 범위(읽기 전용), 수락 기준 AC-01~AC-09를 확인했다. 결정 10개와 버린 대안을 설계 기록에 적었다.
4. **구현.** Claude가 `frontend/`를 썼다. 모듈마다 테스트를 먼저 쓰고 RED를 확인한 뒤 구현했다(Python 훅이 `.ts`를 보지 않으므로 절차로). Vitest 23개, 타입 검사, 빌드가 통과했다. CI에 frontend 작업을 열고, `CLAUDE.md` 명령 절, ADR, `real-env-verify` 스킬(브라우저 환경 점검·검증 패턴)을 갱신했다. Windows → WSL `127.0.0.1` 전달과 preview 프록시는 빈 구독 목록 `200`으로 손으로 확인했다. 커밋 `5cb9d4b`.
5. **실환경 검증 1회차.** real-env-verifier가 AC-01~AC-07, AC-09를 판정해 모두 PASS였다. 리더가 PR #18의 Actions 실행으로 AC-08을 PASS로 확인했다. 수정할 결함은 없었다. 검증 중 막힌 것은 두 가지였다.
   - 처음 두 번 브라우저 확장이 연결되지 않았다(`Browser extension is not connected`). 원인은 Windows에 Chrome이 떠 있지 않은 것이었다(Edge만 실행 중). Chrome을 직접 띄우자 연결됐다. 다음 화면 검증 전에는 Chrome이 떠 있어야 한다.
   - AC-06 중지 직후 스크린숏 한 번이 CDP 30초 시간 초과로 실패했다. 판정은 같은 순간의 화면 글자와 기록기 값으로 했다.
   검증자는 이 회차에서 `backend/tests/e2e/dashboard_watch.py`를 더했다. `backend/tests` 아래라 제품 코드 해시 범위 밖이다.
6. **사람이 내린 결정.** 기능 순서(FR-09 먼저), 프록시, 폴링, 읽기 전용, 수락 기준.

---

## 7. Interview Q&A

### Q1. (개념) Why does your dashboard poll the API instead of getting push updates?

**A.** Because polling is the client model of the contract my API follows, and the API has no push channel. In ARM-style long-running operations, the client gets a tracking URL and polls it until a terminal state. ANF didn't even send Retry-After in the recordings we studied, so the client picks the interval. My dashboard is a bystander, though. It didn't send the requests, so it has no operation URLs. What it can read is the resources, and their bodies carry provisioningState. So it re-reads four list GETs, two seconds after each read ends. Server-Sent Events would mean adding an endpoint that isn't in the ANF contract, and that would change already-verified backend code. So I chose polling.

### Q2. (개념) What does provisioningState tell you, and why can't the dashboard show why a resource failed?

**A.** provisioningState tells you where the resource's last operation stands: Creating, Patching or Deleting while it runs, then Succeeded or Failed. The dashboard shows the string exactly as the API returns it and only picks a color. It can't show the error because the error isn't on the resource. In my API, the code and message live on the operation status, which is where the ARM status contract requires them, and only the client that sent the request has that URL. Showing it would need a read endpoint ANF doesn't have, so I left it out. One caveat: I couldn't confirm whether real ANF marks the resource Failed after an asynchronous failure, so the red badge shows my clone's behavior, not ANF's.

### Q3. (구현) Walk me through the polling hook. What do the cleanup function and the stopped flag do?

**A.** The hook runs one effect per subscription ID. The effect starts a poll loop and returns a cleanup function, which React calls when the subscription changes or the component unmounts. Cleanup does two things: it clears the pending timer, and it sets a stopped flag that belongs to that effect run only, since it's a local variable the closure captures. The flag matters because clearTimeout can't stop a read that's already in flight. When that old read finally returns, the loop checks the flag and exits. So it doesn't write the old subscription's tree over the new one, and it doesn't schedule another timer that nothing could cancel. A unit test covers exactly this: switch subscriptions, resolve the old read late, and the screen stays on the new subscription.

### Q4. (구현) Why did you chain setTimeout instead of using setInterval?

**A.** So that reads never overlap. setInterval fires every two seconds whether or not the last read has finished, because it doesn't wait for a promise. If a full tree read takes three seconds, you end up with several reads in flight. Responses can arrive out of order, so an older tree can overwrite a newer one, and load on the API grows exactly when it's slow. With a chain, the next timer is set only after the current read ends, whether it succeeded or failed. The cost is that the real period is read time plus two seconds. I test it with fake timers: the first read hangs for ten seconds and only one call goes out, then the next call goes out exactly two seconds after it resolves.

### Q5. (설계) What happens when a read fails halfway through the tree?

**A.** The whole round is discarded, and the screen keeps the last complete tree under an error banner. A round is several requests, seven in my verification setup. I treat it as all or nothing because a half-read tree looks like resources were deleted, which is worse than slightly stale data. The hook uses a functional state update, so it keeps the previous tree and timestamp and only sets the error. The "Updated" time freezes, which tells you the data is stale. Polling continues, and the next success clears the banner. There's one exception: a child list that returns 404 means the parent was deleted mid-read, so it counts as empty. In verification, stopping the API showed a 502 banner over the last tree, and a restart cleared it with no reload.

### Q6. (설계) Why a dev-server proxy instead of enabling CORS on the API?

**A.** Mainly to keep the verified API unchanged. The page and the API are on different ports, so they're different origins, and reading API responses from the page would need CORS headers. My API has none. Adding them would change the backend code hash that ties earlier verifications to the code, so finished features would need re-verification over a UI concern. With the Vite proxy, the page calls its own origin and the dev server forwards the request server to server. It also keeps the UI and the API as separate processes. The trade-off is that the dashboard always needs something in front of it; in the container stage, a web server will take over the proxy. One visible side effect: when the API was down, the page saw a 502 from the proxy, not a network error.

### Q7. (한계, 다시 한다면) How far does this design scale, and what would you change?

**A.** It's sized for a demo, and I know where it breaks. Each round costs one request for the accounts plus one per account, per pool, and per volume. In verification that was seven requests per round, but with a few hundred volumes it's hundreds, and the four levels run one after another, so rounds get slower too. Second, latency is the interval plus read time. I measured up to 4.2 seconds, and states shorter than the interval can be missed entirely. Third, the loop keeps running in a hidden tab, where Chrome throttled it. If I did it again, I'd pause on visibilitychange and refresh as soon as the tab is visible again, read only expanded branches, and cancel stale requests with AbortController.

### Q8. (테스트 자동화, 관측성) How did you prove the page updates without a reload, and how did you measure the delay?

**A.** I used two independent recorders on the same clock, plus proof that the page never reloaded. After opening the page once, I planted a marker on the window object, which a reload would erase. At every check, I confirmed it was still there and that there was only one navigation entry. Inside the page, a recorder sampled the DOM every 100 milliseconds. Outside the browser, a Python watcher read the API directly every half second and logged each change with the time of the previous observation. Screen time minus that previous time gives an upper bound on the delay. Across 23 transitions, the maximum was 4.2 seconds, under the five-second limit. Separately, a comparator rebuilt the rows from the API without using any frontend code, and every row matched.

### Q9. (장애·디버깅) Tell me about an unexpected observation during verification and how you explained it.

**A.** Two delays came in at 4.2 seconds, close to the five-second limit, and I wanted to know whether the dashboard was slow. Because the recorder also logged document.visibilityState, I could see both happened while the tab was hidden behind another window. Chrome bunched timers to roughly one-second steps in the hidden tab, which slowed my polling loop and the recorder itself. With the tab visible, the maximum was 2.6 seconds. A second finding: with an instant injected failure, the Patching state lasted about ten milliseconds, so neither the screen nor the API watcher ever saw it, only Failed. That isn't a bug. Polling samples state, it doesn't log transitions. To show the in-progress state too, you inject a delay and the failure together.

### Q10. (테스트, CI) How did you test the React code test-first, and what does CI check?

**A.** I wrote Vitest tests before each module and confirmed they failed first. I had to do that by procedure, because my TDD hook only guards Python files. The polling hook is tested with fake timers, so time is deterministic: one call at 1,999 milliseconds, the second at 2,000, no overlap while a read hangs, and nothing after unmount. The tree reader gets a fake fetch built from a URL table, so an unexpected request fails the test. In CI, a separate frontend job runs npm ci, the type check, the 23 tests, and the build on Node 22. The type check is its own step because Vite's build only transpiles. CI doesn't drive a real browser; that evidence came from the verification round, which is the next gap I'd close.
