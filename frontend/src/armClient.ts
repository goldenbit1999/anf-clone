// anf-api의 목록 GET 네 가지로 리소스 트리를 읽는다 (대시보드 설계 §4).

export const API_VERSION = "2026-08-01";

export interface ArmResource {
  id: string;
  name: string;
  type: string;
  location?: string;
  properties: { provisioningState: string; [key: string]: unknown };
}

/** 깊이가 종류다: 계정 > 용량 풀 > 볼륨 > 스냅샷. */
export interface TreeNode {
  resource: ArmResource;
  children: TreeNode[];
}

type FetchFn = (url: string) => Promise<Response>;

// 부모 id 아래의 자식 목록 경로. 계정부터 차례로.
const CHILD_COLLECTIONS = ["capacityPools", "volumes", "snapshots"];

async function list(url: string, fetchFn: FetchFn, missingIsEmpty: boolean): Promise<ArmResource[]> {
  const response = await fetchFn(`${url}?api-version=${API_VERSION}`);
  // 읽는 사이에 부모가 지워지면 자식 목록이 404다. 실패가 아니라 빈 목록이다 (결정 7).
  if (response.status === 404 && missingIsEmpty) return [];
  if (!response.ok) throw new Error(`GET ${url} returned ${response.status}`);
  return (await response.json()).value;
}

async function node(resource: ArmResource, depth: number, fetchFn: FetchFn): Promise<TreeNode> {
  if (depth >= CHILD_COLLECTIONS.length) return { resource, children: [] };
  const children = await list(`${resource.id}/${CHILD_COLLECTIONS[depth]}`, fetchFn, true);
  return { resource, children: await Promise.all(children.map((c) => node(c, depth + 1, fetchFn))) };
}

/** 구독의 트리 전체를 읽는다. 어느 요청이든 실패하면 전체가 실패한다 (결정 6). */
export async function fetchTree(subscriptionId: string, fetchFn: FetchFn = (url) => fetch(url)): Promise<TreeNode[]> {
  const accounts = await list(
    `/subscriptions/${encodeURIComponent(subscriptionId)}/providers/Microsoft.NetApp/netAppAccounts`,
    fetchFn,
    false,
  );
  return Promise.all(accounts.map((a) => node(a, 0, fetchFn)));
}
