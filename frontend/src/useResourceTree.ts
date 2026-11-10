import { useEffect, useState } from "react";
import { fetchTree, type TreeNode } from "./armClient";

export const POLL_INTERVAL_MS = 2000;

export interface ResourceTreeState {
  /** 마지막으로 성공한 읽기. 아직 한 번도 성공하지 못했으면 null. */
  tree: TreeNode[] | null;
  /** 가장 최근 읽기가 실패했으면 그 메시지. 다음 성공에서 null로 돌아간다. */
  error: string | null;
  updatedAt: Date | null;
}

const EMPTY: ResourceTreeState = { tree: null, error: null, updatedAt: null };

/**
 * 구독의 리소스 트리를 2초마다 다시 읽는다 (대시보드 설계 결정 2).
 * ARM에는 푸시가 없어서 LRO 클라이언트처럼 폴링한다. 한 번의 읽기가 끝난 뒤에 2초를 기다리므로 요청이 겹치지 않는다.
 * 읽기가 실패하면 마지막 트리를 그대로 두고 오류만 알린다 (결정 6).
 */
export function useResourceTree(subscriptionId: string): ResourceTreeState {
  const [state, setState] = useState(EMPTY);

  useEffect(() => {
    setState(EMPTY);
    if (!subscriptionId) return;
    let stopped = false; // 구독이 바뀌거나 화면이 닫힌 뒤 도착한 응답은 버린다
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      try {
        const tree = await fetchTree(subscriptionId);
        if (stopped) return;
        setState({ tree, error: null, updatedAt: new Date() });
      } catch (e) {
        if (stopped) return;
        setState((last) => ({ ...last, error: e instanceof Error ? e.message : String(e) }));
      }
      timer = setTimeout(poll, POLL_INTERVAL_MS);
    }

    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [subscriptionId]);

  return state;
}
