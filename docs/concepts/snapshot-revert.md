# 스냅샷으로 볼륨 되돌리기 (snapshot revert)

> ANF의 revert는 볼륨 전체를 고른 스냅샷 시점으로 되돌리는 비동기 POST 액션이다. 이 클론은 볼륨 인스턴스(knfsd)를 살려 둔 채 그 netns의 입력을 2초 남짓 막고, 고른 스냅샷의 쓰기 가능 스냅샷으로 볼륨 LV를 바꿔 끼운다. 마운트한 클라이언트는 다시 마운트하지 않아도 오류 없이 몇 초 멈췄다가 되돌린 내용을 본다. 설계에서 고른 `lvconvert --merge`는 구현 중 두 번째 되돌리기가 안 돼서 LV 교체로 바뀌었다. 이 문서에서 가장 중요한 이야기다.

FR-06(스냅샷으로 되돌리기)을 다룬다. 대상 코드는 `feature/snapshot-revert` 브랜치의 제품 커밋 `a017d37`(anf-api)과 `597e5a0`(storage agent)이고, 제품 코드 내용 해시 `8cec38bf…`는 검증 시작과 끝이 같다. 공통 비동기 작업(LRO) 계층은 [계정 문서](netapp-account.md), 볼륨 저장 방식(dm-thin)과 볼륨마다 knfsd 인스턴스를 두는 구조는 [볼륨 문서](volume.md), 스냅샷 LV와 `.snapshot` export는 [스냅샷 문서](snapshot.md)에 있다. 이 문서는 그것들을 되돌리기가 어떻게 쓰는지와 새로 생긴 것만 설명한다.

근거 표시는 브리프를 따른다. [스펙]은 Azure REST API 스펙, [문서]는 Microsoft Learn/NetApp 문서, [녹화]는 실서비스 SDK 녹화(문서로 보장되지 않음), [추론]은 해석(사실로 말하면 안 됨), [미확인]은 찾아봤지만 확인하지 못한 것이다. [클론 측정]은 이 프로젝트의 스파이크 S5와 검증자의 측정이다. ANF·ONTAP 사실이 아니라 이 클론의 동작이다.

**이 기능의 조사 상태는 "한도 도달"이다.** 질문 5(revert 중 I/O를 ANF·ONTAP이 어떻게 다루는가)는 조사하지 못했다. 또 ANF·ONTAP 원문 어디에도 이미 마운트한 NFS 클라이언트가 revert를 어떻게 보는지(다시 마운트, stale file handle)가 없다 [미확인]. 그래서 7절 이후 클라이언트 영향에 관한 모든 숫자는 클론의 측정이고, 면접에서는 "공식 언급 없음, 클론 측정값"이라고 말해야 한다.

---

## 1. ANF에서는

- **API.** `POST .../volumes/{volumeName}/revert`, operationId `Volumes_Revert`, 본문은 `{"snapshotId": <스냅샷 ARM ID>}`다 [스펙]. 값은 스냅샷 UUID가 아니라 같은 볼륨 스냅샷의 전체 ARM ID다 [녹화]. 스펙상 `snapshotId`는 필수가 아니고, "같은 볼륨의 스냅샷이어야 한다"는 제약도 스펙에 표현돼 있지 않다 [스펙].
- **응답.** 스펙은 `200`(본문 없음)과 `202`(`Location`, `Retry-After`)이고 최종 결과는 `void`다 [스펙]. 실서비스는 `202`에 본문 없이 `Azure-AsyncOperation`과 `Location`을 보냈고 `Retry-After`는 없었다 [녹화]. 작업 상태는 `Reverting` → `Succeeded`, `action: POST`, 걸린 시간은 약 2.6초(다른 녹화는 폴링 기준 약 5초)였다 [녹화]. 끝난 뒤 `Location`을 GET하면 `200`과 볼륨 본문이 왔다. 스펙의 `void`와 다르다 [녹화].
- **잃는 것.** "Active filesystem data and snapshots taken after the selected snapshot will be lost", "You can't undo reverting a snapshot" [문서]. 고른 스냅샷은 revert 뒤에도 목록에 남았다 [녹화]. 그보다 오래된 스냅샷이 남는지, 더 새 스냅샷이 실제로 지워지는지는 녹화(스냅샷 하나만 만드는 SDK 테스트)로 확인되지 않았고 문서 문구("after")에서 읽은 것이다 [추론].
- **원리와 속도.** 문서는 "near-instantaneous", "The active volume metadata (inode table) is replaced with the snapshot metadata … No data blocks need to be copied"라고 설명한다 [문서].
- **포털.** 스냅샷을 오른쪽 클릭 → Revert volume → 볼륨 이름 입력으로 확인한다 [문서]. API 본문에는 확인 필드가 없다 [스펙].
- **확인하지 못한 것** [미확인]: revert 중 볼륨의 `provisioningState`, revert 전용 오류 코드·문구, 스냅샷 뒤에 크기를 바꾼 볼륨의 `usageThreshold` 처리, 이미 마운트한 클라이언트에 대한 설명, revert 중 I/O 처리.
- **범위 밖 제약** (이름만): 백업이 켜진 볼륨은 백업 기준 스냅샷보다 새 스냅샷으로만, 복제 source 볼륨은 최신 SnapMirror 스냅샷보다 새 사용자 스냅샷으로만 revert할 수 있다 [문서].

## 2. ONTAP에서는

- **대응 기능은 SnapRestore다.** CLI `volume snapshot restore`, REST `PATCH /api/storage/volumes/{uuid}?restore_to.snapshot.uuid=…`이고 응답은 `202`다 [문서]. ANF 문서는 ONTAP 이름을 말하지 않는다. ANF 설명("inode table 교체", "이후 변경 손실")과 ONTAP 설명("replaces the current working copy of the volume with the snapshot that results in a loss of all changes made since the snapshot was created")이 맞아서 같은 기능으로 본다 [추론]. ANF가 ONTAP에 `restore_to.snapshot.uuid`를 넘긴다는 연결도 확인되지 않았다 [추론].
- **복원 뒤 크기.** "the size of the flexible volume will be set to either the current volume size or the snapshot size - whichever is greater" [문서]. ANF의 `usageThreshold`에 이 규칙이 적용되는지는 [미확인].
- **더 새 스냅샷.** ONTAP 원문에 "더 새 스냅샷을 지운다"는 직접 문장은 없다. `-force` 설명과 오류 `1638480`, `9437885`, `9437886`(예: "newer unexpired locked snapshots")이 그 전제를 둬야 성립한다 [추론].
- **복원 오류 예** [문서]: `524511`(복원 실패), `1638480`(더 새 스냅샷이 데이터 보호의 기준 스냅샷), `9437885`("The volume is not online."), `9437886`(잠긴 더 새 스냅샷), 그리고 스냅샷 생성 쪽 `1638532`(revert가 진행 중이라 거절). ANF가 이 코드를 그대로 보여 주는지는 [미확인].
- **WAFL.** 이 기능의 원리를 "WAFL이 active file system의 메타데이터(inode table)를 스냅샷의 것으로 바꾼다"고 설명한 것은 ANF 문서다 [문서]. ONTAP 원문 중 WAFL 내부를 설명한 것은 브리프에 없다 [미확인]. 면접에서 WAFL 내부를 더 말하려면 따로 확인해야 한다.
- **NAS 클라이언트.** ONTAP의 `-preserve-lun-ids`는 LUN·NVMe namespace 식별자에 대해서만 "non-disruptive to clients"를 말한다. NAS 클라이언트가 어떻게 보는지는 ONTAP 원문에도 없다 [문서].

## 3. 이 프로젝트에서는

### 구조

```
POST .../volumes/{v}/revert  {"snapshotId": <ARM ID>}
  anf-api (arm_app.py:286)  -> 검사, 볼륨 Reverting + POST 작업(params에 스냅샷 행 ID), 202 + 두 헤더
  LRO 워커 -> revert 처리기 (volumes.py:528)
     PATCH /api/storage/volumes/{uuid}?restore_to.snapshot.uuid=..&restore_to.request_uuid=<작업 ID>
  storage agent (agent_app.py:161) -> FlexVolManager.restore (flexvol.py:277)
     (1) 진행 표시 태그  (2) 더 새 스냅샷 삭제  (3) 새 볼륨 LV 만들기(창 밖)
     (4) 창: 인스턴스 netns 입력 DROP -> 언마운트 -> 새 LV 마운트 -> export -> DROP 해제
     (5) 옛 LV 삭제, 새 LV 이름 바꾸기(창 밖)  (6) 끝난 표시 태그
  anf-api: 돌려받은 남은 스냅샷 uuid에 없는 스냅샷 행을 지움 -> 작업 Succeeded
```

핵심 아이디어 둘. (a) 인스턴스(knfsd 컨테이너)는 그대로 두고 그 netns의 입력만 잠깐 막는다. 클라이언트는 hard 마운트의 재전송으로 기다린다. (b) 볼륨 LV를 "고른 스냅샷의 쓰기 가능 스냅샷"으로 바꿔 끼운다. 둘 다 구현 전 스파이크 S5와 구현 중 발견으로 정해졌다.

### 코드 따라가기

**1. anf-api: 요청 받기.**
- 라우트 `arm_app.py:286-295`는 본문을 읽고 `volumes.revert_volume`을 부른 뒤 본문 없는 `202`와 추적 헤더 둘을 돌려준다 [녹화 계약을 따름].
- `volumes.py:454-485`의 검사 순서: 이름 → 본문(`parse_revert_body`, `volumes.py:206`) → 스냅샷이 같은 볼륨 아래인지(`volumes.py:461`) → (트랜잭션 안) 볼륨 존재 → 볼륨 진행 중 작업 → 볼륨이 `Succeeded`인지 → 스냅샷 존재 → 그 볼륨 스냅샷에 진행 중 작업이 있는지 → 고른 스냅샷이 `Succeeded`인지. 통과하면 같은 트랜잭션에서 `POST` 작업(`Reverting`)을 만들고 볼륨 `provisioningState`를 `Reverting`으로 쓴다(`volumes.py:481-484`). 고른 스냅샷은 작업 행의 `params`에 남긴다. 이 열은 이 기능에서 새로 생겼다(`state_store.py`의 `Operation.params`).
- 거절 코드(없는 스냅샷 `404`, 다른 볼륨 `400 BadRequest`, 본문 오류 `400 InvalidRequestContent`, 진행 중 `409`)는 ANF 근거가 없는 클론 규칙이다 [미확인].
- 되돌리는 동안 기존 스냅샷의 다시 PUT·DELETE는 `409 Conflict`다(`snapshots.py:95-99`). 되돌리기가 지울 더 새 스냅샷을 동시에 지우거나 다시 만들지 못하게 하려는 것이다. 새 스냅샷 PUT은 기존의 "볼륨이 `Succeeded`가 아님" `400`에 걸린다.

**2. anf-api: agent 호출.**
- 처리기(`volumes.py:528-538`)는 작업 ID를 `restore_to.request_uuid`로 넘긴다. `StorageClient.revert_volume`(`storage_client.py:82-89`)은 PATCH를 보내고 job이 끝나면 agent에 남은 스냅샷 uuid 집합을 돌려받는다. 처리기는 그 볼륨 아래에서 이 집합에 없는 스냅샷 행을 지운다. 이래서 더 새 스냅샷이 ARM 목록에서 사라진다.
- 행 삭제는 처리기 자신의 트랜잭션이다. 지운 뒤 워커가 끝내기 전에 죽으면 재시작 뒤 같은 작업이 다시 실행되고, agent는 끝난 표시를 보고 아무것도 하지 않은 채 같은 목록을 돌려주므로 결과가 같다(설계 §9-6).
- 볼륨 보장 처리기(`volumes.py:512-522`)도 비슷한 정리를 한다. 실패한 revert를 볼륨 PUT이 agent에서 끝내면 더 새 스냅샷이 지워지는데 revert 작업은 이미 `Failed`라 위의 행 삭제가 일어나지 않기 때문이다.

**3. agent: ONTAP 모양의 API.**
- `agent_app.py:161-167`: `PATCH /api/storage/volumes/{uuid}`는 쿼리 `restore_to.snapshot.uuid`와 `restore_to.request_uuid`만 받는다(`agent_app.py:80-92`). 본문은 없거나 `{}`여야 하고, 다른 쿼리나 본문은 `400`이다. ONTAP은 `restore_to.snapshot.uuid` 또는 `.name`을 받고 `202`를 돌려준다 [문서]. `restore_to.request_uuid`는 클론 확장이다.
- job 키는 `PATCH <볼륨 uuid> <키>`다. 볼륨만으로 키를 만들면 anf-api가 60초 재시도 끝에 포기했는데 agent job은 아직 도는 경우, 그 뒤 새 revert가 와서 옛 job을 돌려받는다(설계 §9-3).

**4. agent: `restore` (`flexvol.py:277-299`).**
- 이미 진행 표시(`vol.pending`)가 있으면 그것부터 끝낸다. 그 키가 이번 요청의 키면 끝이다(`flexvol.py:283-288`).
- 볼륨 LV 태그에 이번 키와 같은 `anf_rv_done`이 있으면 이미 끝낸 되돌리기이므로 아무것도 하지 않는다. 그 뒤에 클라이언트가 쓴 데이터를 지우지 않으려는 것이다(`flexvol.py:289-290`).
- 아니면 볼륨이 마운트돼 있는지, 고른 스냅샷이 있는지 확인하고, 볼륨 LV에 진행 표시 태그(`anf_rv_req`, `anf_rv_snap`)를 붙인 뒤 `_resume_restore`를 부른다(`flexvol.py:291-299`).

**5. agent: `_resume_restore` (`flexvol.py:301-340`)** 가 본체다. 남은 LV 모양으로 어디까지 했는지 안다.
- 새 LV가 없으면(`flexvol.py:309`) 먼저 더 새 스냅샷을 지운다. 고르는 기준은 dm-thin 장치 id가 고른 스냅샷보다 큰 것이다(`flexvol.py:311`, id는 `_report`가 `lvs -o thin_id`로 읽는다. `flexvol.py:80`, `413`). id는 "남은 것 중 최댓값 + 1"이라 한 볼륨의 남은 스냅샷끼리는 id 순서가 만든 순서다 [클론 측정 S5 L3]. `anf_snap_time`은 초 단위라 같은 초에 만든 두 스냅샷을 가르지 못해서 쓰지 않았다.
- 그다음 새 볼륨 LV를 만든다(`flexvol.py:316-319`): `lvcreate -s -kn -p rw -n vol_<uuid>_new … <고른 스냅샷 LV>`. 고른 스냅샷의 쓰기 가능 thin 스냅샷이다. 볼륨 태그(`anf_path`, `anf_uuid`, `anf_ip`, `anf_proto`)와 진행 표시와 `anf_rv_new=1`을 만들 때부터 붙인다. 이 시점에 클라이언트는 아직 옛 볼륨을 쓰고 있다(창 밖).
- 창을 연다(`_block_and_unmount`, `flexvol.py:342-353`). 인스턴스 netns 입력을 막고(`instances.block`), 마운트된 스냅샷마다 knfsd의 잠금·NFSv4 상태를 풀고(`unlock_filesystem`) 언마운트한 뒤 볼륨도 같은 순서로 내린다.
- 새 LV를 볼륨 자리에 마운트하고(`_ensure_mounted`), `.snapshot`을 남은 스냅샷에 맞추고(`flexvol.py:324-330`), 남은 스냅샷을 마운트하고, export 파일을 다시 쓴다(`_write_exports`, `flexvol.py:331`). 그 뒤 차단을 푼다(`flexvol.py:332`).
  - `.snapshot` 맞추기가 필요한 이유: 고른 스냅샷을 찍던 때의 `.snapshot` 디렉터리가 돌아오는데, 그 안에는 그 뒤에 지운 스냅샷 이름의 빈 마운트 지점이 있을 수 있고 고른 스냅샷 자신의 마운트 지점은 없다.
- 창 밖: 옛 볼륨 LV를 `lvremove`하고(`flexvol.py:335`), 새 LV를 `vol_<uuid>`로 `lvrename`한다(마운트된 채 된다, `flexvol.py:336-337`). 마지막으로 진행 표시를 지우고 `anf_rv_done=<키>`를 남긴다(`flexvol.py:338-339`).
- `_report`(`flexvol.py:410-`)는 이 사이에 한 볼륨에 LV가 둘(옛 것과 `anf_rv_new` 새 것)인 상태를 한 볼륨으로 읽는다. 옛 LV가 있으면 그것이 볼륨이다.

**6. 창: `nfs_instance.py:161-187`.**
- `block`은 `docker inspect`로 인스턴스의 pid를 얻고 `nsenter -t <pid> -n iptables -I INPUT -i eth0 -j DROP`을 넣는다. 넣기 전에 `-C`로 있는지 봐서 재시도해도 규칙은 하나다. 이어서 인스턴스 안에서 `exportfs -f`로 커널 export 캐시를 비운다. `unblock`은 규칙이 있는 동안 `-D`한다.
- 이미지에 iptables가 없어도 호스트의 iptables로 들어가는 방식이다(설계 결정 13). 인스턴스가 지워지면 netns와 DROP 규칙도 같이 사라진다.

**7. 호스트 준비: 위임 끄기.**
- `check_host`(`nfs_instance.py:79-84`)는 `fs.leases-enable`이 0이 아니면 agent를 띄우지 않는다. 준비 스크립트 `scripts/setup-wsl-dataplane.sh`가 `sysctl -w fs.leases-enable=0`을 하고 `/etc/sysctl.d/90-anf-clone.conf`에 고정한다(`iptables`·`nsenter` 존재도 확인한다).

**8. 위험 지점 둘의 방어.**
- 진행 표시가 남은 볼륨에는 agent의 스냅샷 생성·삭제를 거절한다(`flexvol.py:363-369`). 새 LV를 만들기 전에 스냅샷을 만들면 이어서 끝낼 때 그 스냅샷이 "더 새 스냅샷"으로 지워지고, 고른 스냅샷을 지우면 새 LV를 만들 수 없기 때문이다(설계 §9-4).
- 스냅샷 삭제 절차(`_remove_snapshot`, `flexvol.py:371-381`)는 스냅샷 기능의 것을 그대로 재사용한다: export 줄 제거 → 잠금 해제 → 언마운트 → 마운트 지점 → `lvremove`.

### 설계 결정

| 결정 | 버린 대안 | 이유 |
| --- | --- | --- |
| 창 방식: 인스턴스는 두고 netns 입력만 DROP (사용자가 선택) | export를 잠깐 빼기 | v3 클라이언트가 창 동안 `Permission denied`를 받는다 (S5 R, 탐침 20회 넘게 실패). 줄이 없는 동안 mountd가 그 `fsid`를 거절한 것으로 본다 [추론] |
| (같은 결정) | 인스턴스 재시작 | v4.1이 23 s 멈추고, 재시작한 knfsd의 유예 기간에 클라이언트가 읽기 위임을 되찾아(reclaim) 재시작 뒤 65 s가 지나도 옛 내용을 읽었다 (S5 R). 데이터를 틀리게 보여 주는 방식이다 |
| **볼륨 LV 교체: 고른 스냅샷의 쓰기 가능 스냅샷을 새 볼륨으로 (구현 중 변경)** | `lvconvert --merge` + 고른 스냅샷 다시 만들기 (사용자가 설계에서 선택) | merge 뒤 남은 스냅샷은 원본 표시(`origin`)를 잃고 LVM은 원본이 현재 볼륨인 thin 스냅샷만 merge한다. 그래서 한 번 되돌린 볼륨을 첫 되돌리기 전부터 있던 더 오래된 스냅샷으로 다시 되돌릴 수 없다. 5절 참고 |
| NFSv4 위임을 끈다 (`fs.leases-enable = 0`, 사용자가 선택) | knfsd 기본값(위임 켬) | 위임을 가진 v4.1 클라이언트는 서버에 묻지 않고 캐시를 믿는다. `unlock_filesystem`은 위임을 서버에서 회수(revoke)할 뿐 클라이언트에 알리지(recall) 않아서 열린 fd가 16~32 s 동안 되돌리기 전 내용을 읽었다 (S5 B2). 끄면 v3처럼 바로 맞다 |
| 멱등 키 = anf-api 작업 ID를 `restore_to.request_uuid`로, 진행·끝 표시를 LVM 태그에 (사용자가 선택) | 단순 재실행 | anf-api가 agent 완료와 기록 사이에 죽으면 같은 되돌리기를 한 번 더 해서 첫 되돌리기 뒤에 쓴 데이터가 사라진다 |
| 더 새 스냅샷을 dm-thin 장치 id로 고른다 | `anf_snap_time` 순서, anf-api의 `created` 순서 | 초 단위라 같은 초에 만든 스냅샷을 가르지 못한다. 데이터 플레인의 사실을 컨트롤 플레인이 추측하게 된다 |
| 볼륨이 되돌리는 동안 `provisioningState: Reverting` (사용자가 선택) | `Succeeded` 유지 | 실패해도 볼륨이 정상처럼 보이고 충돌 검사가 작업 표에만 기댄다. ANF의 실제 값은 [미확인] |
| ARM 계약은 녹화를 따름: 본문 없는 `202`, 두 헤더, 최종 `Location` GET은 볼륨 본문 | 스펙의 `Location` + `Retry-After`, 최종 `void` | 실서비스와 같게 하려고. 스펙과 다른 점은 기록한다 |
| 작업 입력을 `operations.params`(JSON)에 | `previous` 재사용, 볼륨 `properties`에 넣기 | `previous`는 "UPDATE 실패 시 되돌릴 값"이라는 뜻이 다르다. `properties`는 볼륨 본문에 그대로 보인다 |
| 창의 DROP은 호스트에서 `nsenter` | 이미지에 iptables를 넣고 `docker exec` | 이미 떠 있는 옛 이미지의 인스턴스에는 없다 |

## 4. 실제 ANF와 다른 점

| 항목 | 실제 ANF | 이 프로젝트 | 이유 |
| --- | --- | --- | --- |
| 되돌리는 원리 | inode table(메타데이터)을 스냅샷 것으로 교체, 블록 복사 없음 [문서] | 볼륨 LV를 고른 스냅샷의 쓰기 가능 thin 스냅샷으로 바꿔 끼움. 블록은 새 LV와 스냅샷이 공유하고 이후 쓰기에서 청크 단위로 갈린다 | dm-thin에는 WAFL 같은 inode table 교체가 없다. "효과가 같다"고 말하고 "구현이 같다"고 말하지 않는다 |
| 시간 | 약 2.6 s [녹화], 가장 큰 볼륨도 몇 초 [문서] | ARM 작업 4.15~5.16 s, 클라이언트가 3.35 s 멈춤 | 창이 1.95 s이고, 창 밖에서 옛 LV 삭제·이름 바꾸기·태그에 약 1.5 s가 더 든다. 반복은 각 1~6회뿐이다 |
| 클라이언트 영향 | [미확인] | 다시 마운트 불필요, 오류 0, 몇 초 멈춤 | ANF·ONTAP 원문에 없다. 클론 측정이 유일한 근거다 |
| NFSv4 위임 | ANF 설정 [미확인]. ONTAP REST 기본값은 읽기·쓰기 위임 꺼짐 [문서(S5가 인용한 ONTAP nfs_service 모델)] | 꺼짐, WSL VM 커널 전역(`fs.leases-enable = 0`) | knfsd에는 인스턴스(netns)별 위임 설정이 없다. 이 값은 WSL VM 안 모든 배포판의 파일 lease를 끈다 |
| 더 새 스냅샷 | 사라진다 [문서], 어느 기준으로 고르는지 [미확인] | dm-thin 장치 id가 더 큰 것. 데이터 없는 `Failed` 스냅샷 행도 되돌리기 뒤 함께 지워진다 | 클론의 선택. 설계 기록 결정 8, §9-5 |
| 되돌리는 동안 다른 요청 | [미확인] (ONTAP은 스냅샷 생성을 `1638532`로 거절) | 볼륨 PUT·PATCH·DELETE·revert `409 RequestConflict`, 새 스냅샷 `400 BadRequest`, 기존 스냅샷 PUT·DELETE `409 Conflict` | 클론 규칙 |
| 거절 코드·문구 | [미확인] | 본문 오류 `400 InvalidRequestContent`, 다른 볼륨 `400 BadRequest`, 없는 스냅샷 `404 ResourceNotFound`(스냅샷 GET의 녹화 문구) 등 | 클론 규칙 |
| `snapshotId` 필수 여부 | 스펙상 선택 [스펙] | 필수 | 없으면 무엇으로 되돌릴지 정할 수 없다 |
| 최종 `Location` GET | 스펙은 `void`, 녹화는 `200` + 볼륨 본문 | 녹화대로 | |
| 크기 규칙 | ONTAP은 max(현재, 스냅샷 시점) [문서], ANF는 [미확인] | `usageThreshold`를 바꾸지 않음 | 크기 변경 기능(FR-16)이 아직 없어서 둘은 늘 같다. 그 기능에서 연다 |
| 백업·복제 제약 | 있음 [문서] | 해당 기능이 없다 | 범위 밖 |
| 공간 | 스냅샷 공간이 볼륨 할당량에 포함 [문서] | 스냅샷과 새 LV가 thin pool에서 공간을 쓴다. 스냅샷이 사라지거나 새로 생겨도 볼륨 크기는 안 변한다 | dm-thin 구조 (스냅샷 문서의 공간 차이와 같은 이야기) |
| 창 안에서 agent가 죽을 때 | [미확인] | hard 마운트 클라이언트는 agent가 돌아와 창을 닫을 때까지 멈춘다. 그 뒤 TCP 재전송 대기가 더 붙는다 | 5절의 관찰. 설계 §6.2대로 agent 시작 복구가 창을 닫는다 |

## 5. 구현 중 설계가 뒤집힌 이야기: merge에서 LV 교체로

면접에서 "무엇이 잘못됐고, 어떻게 찾았고, 무엇을 바꿨나"로 나올 가능성이 높다.

**설계에서 선택한 것.** 사용자가 "네트워크 차단 + `lvconvert --merge` + 고른 스냅샷 다시 만들기"를 골랐다. 근거는 스파이크 S5였다. 모두 언마운트한 뒤의 `lvconvert --merge`는 0.4~0.6 s에 끝났고 볼륨 LV의 이름·태그가 그대로라서 agent의 볼륨 식별(LVM 태그)이 바뀌지 않았다. merge는 고른 스냅샷 LV를 소비하므로 되돌린 볼륨에서 같은 태그로 다시 만든다. LV 교체는 S5에서 L2로 시험됐고 "`lvrename` 두 번에 3 s, 볼륨 태그를 옮겨야 한다"는 이유로 후보에서 밀려 있었다.

**무엇이 잘못됐나.** 가짜 호스트를 쓴 단위 테스트는 통과했다. 첫 통합 테스트(실제 LVM)에서 s1·s2·s3를 만들고 s2로 되돌린 다음 더 오래된 s1로 다시 되돌리자 `lvconvert --merge anf/snap_<s1>`이 `is not a mergeable logical volume`(rc 5)으로 실패했다.

**원인.** S5 L3이 이미 본 현상의 결과였다. merge가 끝나면 남은 스냅샷은 `origin` 표시를 잃는다(S5 L3: "A는 `origin` 표시가 없어진 채 남는다"). 그리고 LVM은 원본이 현재 볼륨인 thin 스냅샷만 merge한다. 그래서 첫 되돌리기 전부터 있던 스냅샷으로는 두 번째 되돌리기를 할 수 없다. 스파이크는 한 번 되돌리는 시나리오만 시험했고 그 관찰(원본 표시 소실)이 두 번째 되돌리기에 미치는 영향을 연결하지 못했다.

**어떻게 찾았나.** 테스트가 실제 LVM을 쓰는 통합 층에 있었기 때문이다. 단위 테스트의 가짜 호스트는 LVM의 이 규칙을 모른다. 이것이 "단위는 통과, 통합이 잡음"의 사례다.

**무엇을 바꿨나.** S5 L2의 교체 방식을 채택했다. 쓰기 가능 스냅샷(`lvcreate -s -kn -p rw`)은 원본 관계와 상관없이 어느 thin 스냅샷에서나 만들 수 있다. 교체 방식을 버렸던 이유 둘을 이렇게 덜었다.
- "`lvrename` 두 번에 3 s": 옛 LV를 지운 뒤 한 번만 하고 차단을 푼 뒤(창 밖) 한다.
- "볼륨 태그를 옮겨야 한다": 새 LV를 만들 때(창 밖) 처음부터 붙인다. 그래서 옛 LV를 지운 순간에도 볼륨 정체성이 사라지지 않는다.

**바뀌지 않은 것**: 사용자가 고른 것 중 netns 입력 차단, 인스턴스 유지, 다시 마운트 없음, 고른 스냅샷 유지는 그대로다. 그리고 창 안에는 언마운트·마운트·export만 남는다(merge 방식에서는 `lvconvert`와 `lvcreate`도 창 안이었다). 부수 효과로 고른 스냅샷 LV를 건드리지 않으니 그 LV·태그·ARM `snapshotId`·`created`가 그대로이고, "다시 만들 정보"를 태그에 미리 적어 둘 필요(`anf_rv_name`, `anf_rv_time`, dm-thin id 표시)와 "미뤄진 merge"(S5 L1a)라는 실패 경로가 없어졌다.

**주의할 점.** LV 교체로 바뀐 뒤에도 파일 핸들이 유지되는 이유(6절)는 같은 이유로 성립한다. 검증자는 교체 방식의 남은 위험도 시험했다. 되돌린 볼륨 LV의 원본인 스냅샷을 삭제하면 `origin`이 빈 값이 되지만 볼륨 트리는 그대로였고, WSL 재시작을 흉내 낸 `lvchange -an` 뒤 agent가 모두 다시 켰다 [검증 기준 밖 관찰 1].

## 6. 클라이언트에서 어떻게 보이는가와 그 이유 (클론 측정, ANF·ONTAP 근거 없음 [미확인])

- **다시 마운트하지 않아도 된다.** 되돌리기 전부터 마운트한 클라이언트가 마운트 줄(`/proc/mounts`) 그대로 오류 없이 이어 쓴다.
- **스냅샷에 있던 파일·디렉터리**는 열린 fd와 cwd까지 그대로 이어지고 스냅샷 시점 내용을 읽는다. **스냅샷 뒤에 만든 파일·디렉터리**를 잡고 있던 fd·cwd만 `Stale file handle`이고, 경로로 찾으면 `No such file or directory`다.
- **왜 핸들이 유지되는가** [추론, S5]: NFS 파일 핸들은 export의 `fsid` + inode 번호 + inode 세대다. 볼륨 export의 `fsid`는 볼륨 UUID로 고정이고, 새 볼륨 LV의 ext4는 고른 스냅샷의 inode 표 그대로라서 그때 있던 파일은 같은 핸들로 찾아진다. 스냅샷 뒤에 만든 파일의 inode는 되돌린 파일시스템에 없거나 세대가 달라 `ESTALE`이다. WAFL SnapRestore가 inode table을 바꾸는 것과 같은 모양이다 [문서 7과 대조한 추론].
- **왜 위임을 껐나.** knfsd는 기본으로 NFSv4 위임을 준다. v4.1 클라이언트가 쓰기 위임을 가진 채 `unlock_filesystem`으로 서버 쪽 위임이 회수(revoke)되면, 클라이언트는 알림 없이 다음 lease 갱신 때(lease 30 s) 알아채고 캐시를 버린다 [추론: 열린 fd가 16~32 s 사이에 바뀜]. 그동안 열린 fd는 되돌리기 전 캐시를 읽었다(S5 B2: `b2 b2 b2 b2 b2 b1 b1`). `fs.leases-enable = 0`이면 knfsd 위임이 VFS lease 위에서 돌아서 위임이 아예 안 나가고, v4.1도 바로 맞는다.
- **ONTAP의 기본값**은 NFS 서비스 모델에서 읽기·쓰기 위임이 꺼짐이다 [S5가 인용한 ONTAP 모델]. ANF가 위임을 켜는지는 [미확인].

## 7. 검증 (1회차, PASS 11 / FAIL 0 / UNVERIFIED 0)

검증자(구현자와 다른 에이전트)가 WSL 실환경에서 root로 e2e를 돌렸다. 대상 코드 해시는 시작과 끝이 같다(`8cec38bf…`). 제품 코드는 고치지 않았고 e2e 테스트(`revert_live.py`, `test_snapshot_revert_data_live.py`, `test_snapshot_revert_contract_live.py`)를 더했다.

| 기준 | 내용 | 결과 |
| --- | --- | --- |
| AC-01 | `202`, 본문 없음, `Azure-AsyncOperation`·`Location`(`Retry-After` 없음). 폴링은 `Reverting`(`action: POST`) → `Succeeded`, 지연 중 볼륨 GET은 `Reverting`, 끝난 뒤 `Location` GET은 `200` + 볼륨 본문 | PASS |
| AC-02, 03 | v3·v4.1: 되돌린 볼륨 트리 체크섬 = 되돌리기 전 S2 트리. S1·S2는 `snapshotId`·`created`까지 그대로, S3는 GET `404`, `.snapshot/S3` 없음, LV·마운트·export 줄 없음. 되돌린 뒤 쓰기와 새 스냅샷도 됨 | PASS |
| AC-04 | 마운트한 클라이언트 (아래) | PASS |
| AC-05 | 거절 10종, 작업이 생기지 않고 데이터 그대로 | PASS |
| AC-06 | 진행 중 충돌 `409`/`400`, 진행 중이던 revert는 `Succeeded`로 끝남 | PASS |
| AC-07 | 실패 주입, agent 중단(60.3 s 재시도 뒤 `Failed`) → 볼륨 PUT으로 회복 | PASS |
| AC-08 | 재시작 안전: anf-api SIGKILL, 같은 키 재전송, 중간 정지 5경우(통합), 창 안 agent SIGKILL, 더 오래된 스냅샷으로 두 번째 되돌리기 | PASS |
| AC-09 | agent PATCH API와 거절 | PASS |
| AC-10 | 위임 꺼짐: `deleg` 상태 없음, 값 1이면 agent가 뜨지 않음 | PASS |
| AC-11 | 회귀: e2e 102 passed, 통합 17 passed, 단위·계약 741 passed (skip 0) | PASS |

**AC-04 측정(마운트한 클라이언트, 각 1회).**
- 서버 쪽 창(DROP 규칙이 있던 시간): v3 1.956 s, v4.1 1.952 s.
- 0.2 s마다 하는 기존 파일 읽기: v3 39회, v4.1 38회, **실패 0**. 가장 긴 멈춤은 v3 3.364 s, v4.1 3.352 s.
- 되돌리는 동안 계속 쓰는 클라이언트: 67회 모두 성공, 구멍(NUL) 없음. S2 뒤에 쓴 `w1`~`w26`은 되돌리기로 사라졌고, 창이 열린 직후 시작한 `w27`은 3.45 s 멈췄다가 성공해 되돌린 볼륨에 들어갔다. 설계의 추론("창 동안 도착한 쓰기는 되돌린 볼륨에 들어간다")과 맞는다.
- 열린 fd와 cwd: 6절과 같았다(S2에 있던 것은 이어지고 S2 뒤에 만든 것만 `Stale file handle`).

**멈춤이 창보다 긴 이유** [추론]: 창은 netns 입력 DROP이라 클라이언트의 TCP는 응답 없는 재전송 간격을 두 배씩 늘린다. 첫 RTO를 약 0.23 s로 두면 재전송이 창 열린 뒤 0.23, 0.69, 1.61, 3.45, 7.1, 14.5, 29, 58, 117 s에 나간다. 측정과 맞는다(창 1.95 s → 멈춤 3.35 s, 창 7.76 s → 13.49 s, 창 72.63 s → 117.21 s). 클라이언트는 창이 닫힌 뒤 다음 재전송까지 기다린다. 첫 RTO 값은 측정에서 맞춘 값이고 TCP 구현에서 직접 확인한 것이 아니다.

**창 안에서 agent가 죽은 경우(AC-08c)** 데이터 플레인은 복구되지만 클라이언트는 오래 멈춘다. agent를 창 안에서 죽였다가 8.7 s 뒤에 띄운 경우(v4.1)는 창 7.76 s, 가장 긴 멈춤 13.49 s였다. 73.6 s 뒤에 띄운 경우(v3)는 anf-api 작업이 먼저 `Failed`가 됐고(볼륨 `Failed`), agent 시작 복구가 창을 닫았으며, 볼륨 PUT으로 `Succeeded`와 S3 행 삭제까지 끝났다. 그동안 클라이언트는 오류 없이 117.21 s 멈췄다. 운영상 의미가 있는 관찰이다.

**ARM 작업 시간**: 4.15~5.16 s(6회), 버린 첫 실행에서 v3 한 번 8.75 s였다(원인은 안 봤다). 실서비스 녹화는 약 2.6 s [녹화]. 창이 닫힌 뒤 `Succeeded`까지 약 1.5 s(옛 LV 삭제, 이름 바꾸기, 태그, anf-api의 job 폴링)다.

**검증이 한 일 중 짚을 것.** 실패한 실행 둘은 제품 결함이 아니었다. 기대값에 `lost+found`를 잘못 적은 것(agent의 루트 초기화가 지운다), 창이 닫힌 뒤에도 막혀 있던 탐침을 너무 일찍 읽은 것이었다. AC-10에서는 값을 잠깐 1로 바꿔 `deleg` 상태가 실제로 보이는지 대조해서, "deleg 없음"이 검사가 헛돌아서가 아님을 보였다. "볼륨 POST(보장)가 같은 중간 상태를 끝낸다"는 통합 테스트로만 확인했다. e2e에서는 agent가 떠 있는 채 진행 표시가 남는 상태를 결함 주입 없이 만들 수 없다.

## 8. 개발 과정

1. **조사.** anf-researcher가 ARM 계약과 녹화(R3), 문서의 제약, ONTAP SnapRestore를 조사했다. 첫 실행은 원문만 모으고 30턴 한도에 닿았고, 같은 에이전트에 새 원문 없이 브리프를 쓰라고 이어 맡겼다. 질문 5(revert 중 I/O)는 끝내 못 했다. revert 전용 오류 코드, revert 중 볼륨 `provisioningState`, 크기 규칙, 클라이언트 영향이 [미확인]으로 남았다. 설계를 막지 않는다고 판단해 클론 규칙으로 정하고 차이를 기록하기로 했다. 브리프는 스냅샷 브리프의 "볼륨이 `Reverting`"이 사실은 작업 상태였다는 점도 바로잡았다.
2. **스파이크 S5.** 조사와 병행했다. S1의 되돌리기 시험은 마운트한 클라이언트 때문에 `umount`가 `busy`라 끝나지 않았고, 그 뒤 구조가 볼륨마다 knfsd 인스턴스로 바뀌었다(D-12). 그래서 설계 전에 새 구조에서 창 방식 셋(export 제거, 인스턴스 재시작, netns 차단)과 LVM 동작을 쟀다. 결과: netns 차단만 오류 없이 통과, NFSv4 위임이 열린 fd에 옛 내용을 보이게 한다는 것, dm-thin id가 생성 순서라는 것.
3. **설계.** **사람이 내린 결정**: 네 선택지 모두 추천안을 골랐다(위임 끄기, 되돌리는 동안 볼륨 `Reverting`, 네트워크 차단 + merge + 다시 만들기, 작업 ID를 멱등 키로). 나머지 기본안(녹화 계약, 거절 규칙, dm-thin id, `operations.params`)에는 이견이 없었다.
4. **구현.** Claude가 TDD 훅 아래서 두 커밋으로 나눠 구현했다. anf-api(`a017d37`)를 먼저, storage agent(`597e5a0`)를 그다음에. **설계가 뒤집힌 것이 이 단계에서 나왔다**(5절). 단위는 통과하고 통합 테스트가 merge의 한계를 잡았다. 메인이 사용자가 고른 LVM 부분만 바꾸고 나머지는 지켰으며, 그 이유와 바뀐 8가지를 설계 §9에 적고 S5·ADR·PRD·CLAUDE.md를 맞췄다. 구현 후 Windows 전체 741 passed(Linux 전용 119 skip), WSL 통합 17 passed.
5. **검증 1회차.** 검증자가 AC-01~AC-11을 실환경에서 확인해 11 PASS. 제품 결함은 없었다. 멈춤 시간과 TCP 재전송, 창 안 agent 사망의 영향을 기준 밖 관찰로 남겼다.
6. **개념 문서(이 문서).**

AI와 일한 방식으로 설명할 수 있는 것: 조사가 일부 비어도(질문 5) 스파이크로 클론의 사실을 직접 재고, 그 측정값을 "ANF·ONTAP 근거 없음"이라고 표시한 채 설계 근거로 썼다. 사용자가 고른 설계가 실제 LVM의 규칙에 막혔을 때 이유를 기록하고 필요한 부분만 바꿨다. 구현자와 다른 에이전트가 실환경에서 검증했다.

## 9. Interview Q&A

### Q1. (개념) What happens when you revert an ANF volume to a snapshot, and what is the ONTAP equivalent?

**A.** Revert replaces the whole volume with the data and timestamps from the chosen snapshot. Everything written after it, including newer snapshots, is lost, and you cannot undo it. The API is `POST .../volumes/{v}/revert` with the snapshot's ARM ID in the body. The recorded service returns a bodyless 202 with two tracking headers, and the operation goes `Reverting` to `Succeeded` in about 2.6 seconds. ANF's docs say it replaces the inode table with the snapshot metadata and copies no data blocks. The ONTAP equivalent is SnapRestore, REST `PATCH /api/storage/volumes/{uuid}?restore_to.snapshot.uuid=...`. The docs never name ONTAP, so I call the mapping an inference.

### Q2. (개념) What do NFS clients see during and after a revert, and what do the official sources say?

**A.** The official sources say nothing about it, so I measured my clone and I label it that way. A client mounted before the revert does not need to remount. A hard-mount client stalled about 3.4 seconds with zero errors, while the server-side window was 1.95 seconds. After that, files that existed in the snapshot read the snapshot content, including already-open file descriptors and working directories. Only handles to files or directories created after the snapshot return `Stale file handle`, and their paths return `No such file or directory`. I explain this as: the file handle is fsid plus inode number plus generation, and my fsid is fixed, so it follows the inode table. That explanation is an inference.

### Q3. (설계) Why do you keep the NFS instance running and only block its network input, instead of removing the export or restarting it?

**A.** Because I measured all three in spike S5, and only the network block worked cleanly. Removing the export made NFSv3 reads fail with `Permission denied` during the window. Restarting the instance made NFSv4.1 stall 23 seconds, and after the restart the client reclaimed its read delegation, so it kept reading old content even 65 seconds later. Blocking input with iptables inside the instance's netns, entered via `nsenter` from the host, costs nothing but retransmissions. Hard-mount clients wait, and I saw zero errors for both protocols. The code is `block` and `unblock` in `nfs_instance.py`. The rule is checked with `-C` before insertion, so a retry never stacks rules.

### Q4. (설계) Why did you turn NFSv4 delegations off globally, and what does ONTAP do?

**A.** With delegations on, a v4.1 client that holds a delegation trusts its cache without asking the server. My window calls `unlock_filesystem`, which revokes the delegation on the server but does not recall it from the client. In the spike, an open file descriptor kept returning pre-revert data for 16 to 32 seconds, until I guess the client noticed at its next lease renewal. That timing is an inference. With `fs.leases-enable = 0`, no delegations are granted and v4.1 behaves like v3. knfsd has no per-instance setting, so it is kernel-wide for the whole WSL VM, and the agent refuses to start otherwise. ONTAP's NFS service model defaults to read and write delegations disabled. Whether ANF enables them is unconfirmed.

### Q5. (설계) How does a repeated PATCH, a volume POST, or a restart finish an interrupted revert without running it twice?

**A.** anf-api passes its operation ID as an idempotency key, `restore_to.request_uuid`, which is a clone extension to ONTAP's API. The agent stores state in LVM tags, so there is no database to disagree with the system. It tags the volume LV with the request and the chosen snapshot first. The new LV carries the volume's tags from creation, so the volume is never unidentifiable. When the revert finishes, the agent replaces the markers with `anf_rv_done=<key>`. A repeated key then does nothing, and it does not erase data written after the first revert. A half-finished state is read from the LVs that exist: no new LV, or both LVs, or only the new one. The verifier killed the agent inside the window, and also tested five stop points.

### Q6. (트레이드오프) Where does your revert differ from real ANF?

**A.** Mainly the mechanism and the client-visible pause. ANF's docs describe replacing the inode table, so no data is copied. In my clone the volume LV is replaced with a writable thin snapshot of the chosen snapshot, so it is a different implementation with a similar effect. The ARM operation took 4 to 5 seconds versus about 2.6 in the recording, and clients pause about 3 seconds, while ANF's behavior for clients is unconfirmed. I disable NFSv4 delegations VM-wide, which ANF may not do. I choose newer snapshots by dm-thin device ID, and I do not apply ONTAP's rule that the volume size becomes the larger of current and snapshot size, because resize does not exist yet. Rejection codes are my own rules, since I found none for ANF.

### Q7. (디버깅) What went wrong during the implementation, how did you find it, and what did you change?

**A.** My chosen design used `lvconvert --merge`, and the unit tests passed. The first integration test on real LVM reverted to a newer snapshot, then to an older one, and the second merge failed with `is not a mergeable logical volume`. After a merge, the other snapshots lose their origin link, and LVM only merges thin snapshots whose origin is the current volume. So a volume could not be reverted twice to snapshots that predate the first revert. The unit tests used a fake host and could not know this LVM rule. I switched to creating a writable snapshot of the chosen snapshot as the new volume LV, tagged from the start, then removing the old LV and renaming. The chosen snapshot also stays untouched. I recorded the reason in the design file.

### Q8. (다시 한다면) If you did it again, what would you change?

**A.** Two things. First, the spike only tested one revert, and I should have tested a second revert to an older snapshot, since the spike had already shown that merge drops origin links. I would write the multi-step scenario in the spike. Second, I would reduce the client stall. The stall was 3.4 seconds because TCP backs off while input is dropped, and if the agent dies inside the window it can reach 117 seconds in my test. Rejecting packets instead of dropping them, or shortening the window, are options I did not test. The backoff explanation itself is an inference that matches three measurements. I would also confirm the unknowns, such as revert's error codes and the volume state during revert, against a real ANF if I could.

### Q9. (테스트/관측) How did you verify a feature that spans REST, an agent, LVM, and the kernel, and how did you make claims about client behavior?

**A.** In layers. Unit tests use a fake command runner for ordering. Contract tests check status codes, headers, and bodies against a fake agent. Integration tests use real LVM, and that layer found the merge limitation. A separate verifier ran end-to-end tests with NFS client containers for v3 and v4.1: a probe reading every 0.2 seconds, a writer, open descriptors, and a watcher polling the DROP rule every 0.02 seconds, so the server window of 1.95 seconds and the client stall of 3.4 seconds were measured separately. Pass or fail used exit codes and full stderr. For the claims about client behavior, there is no ANF source, so every number is labeled as a clone measurement, and I show the repeats: mostly one run each, six for operation time.

### Q10. (REST/LRO) How does your revert API follow the ARM long-running operation style, and where did you follow the recording over the spec?

**A.** The POST returns 202 with no body, and two headers, `Azure-AsyncOperation` and `Location`, with no `Retry-After`. That matches the recording. The spec instead lists `Location` plus `Retry-After`, and a final result of void. The operation status goes `Reverting` to `Succeeded` with `action: POST`, and after completion a GET on `Location` returns 200 with the volume body, again as recorded. While reverting, the volume itself reports `Reverting`, which is my choice, since ANF's value is unconfirmed. The write and the operation row are stored in one transaction, and the worker finishes it. After a restart it re-runs unfinished operations, and the idempotency key makes that safe.
