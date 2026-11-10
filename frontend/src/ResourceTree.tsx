import type { ArmResource, TreeNode } from "./armClient";

const GIB = 1024 ** 3;
const TIB = 1024 * GIB;

type Props = ArmResource["properties"];

// 깊이별 종류 이름과 속성 요약. 값은 API가 준 것을 형식만 바꿔 보인다.
const KINDS: { label: string; details: (resource: ArmResource) => string[] }[] = [
  {
    label: "NetApp account",
    // .../resourceGroups/{rg}/providers/Microsoft.NetApp/netAppAccounts/{name}
    details: (r) => [r.id.split("/")[4], r.location ?? ""],
  },
  {
    label: "Capacity pool",
    details: ({ properties: p }) => [
      `${Number(p.size) / TIB} TiB`,
      String(p.serviceLevel),
      `${p.qosType} QoS`,
      `${p.utilizedThroughputMibps} / ${p.totalThroughputMibps} MiB/s`,
    ],
  },
  {
    label: "Volume",
    details: ({ properties: p }) => [
      mountPath(p),
      (p.protocolTypes as string[]).join(", "),
      `${Number(p.usageThreshold) / GIB} GiB`,
      `${p.actualThroughputMibps} MiB/s`,
    ],
  },
  {
    label: "Snapshot",
    details: ({ properties: p }) => [String(p.created ?? "")],
  },
];

/** NFS 클라이언트가 마운트할 `<IP>:/<creationToken>`. mountTargets는 볼륨 생성이 성공한 뒤에 생긴다. */
function mountPath(p: Props): string {
  const targets = p.mountTargets as { ipAddress: string }[] | undefined;
  return targets?.length ? `${targets[0].ipAddress}:/${p.creationToken}` : "";
}

/** 배지 색만 나눈다. 글자는 API의 provisioningState 그대로다 (설계 §5). */
function stateClass(state: string): string {
  if (state === "Succeeded") return "ok";
  if (state === "Failed") return "failed";
  return "busy";
}

function rows(nodes: TreeNode[], depth: number): React.ReactNode[] {
  return nodes.flatMap(({ resource, children }) => {
    const kind = KINDS[depth];
    const state = resource.properties.provisioningState;
    return [
      <tr key={resource.id} aria-level={depth + 1}>
        {/* 풀·볼륨·스냅샷의 name은 "계정/풀/..." 형식이라 마지막 조각만 보인다 */}
        <td style={{ paddingLeft: `${depth * 1.5 + 0.5}rem` }}>{resource.name.split("/").pop()}</td>
        <td>{kind.label}</td>
        <td>
          <span className={`state ${stateClass(state)}`}>{state}</span>
        </td>
        <td>{kind.details(resource).filter(Boolean).join(" · ")}</td>
      </tr>,
      ...rows(children, depth + 1),
    ];
  });
}

export function ResourceTree({ tree }: { tree: TreeNode[] }) {
  if (tree.length === 0) return <p className="empty">No NetApp accounts in this subscription.</p>;
  return (
    <table role="treegrid">
      <thead>
        <tr>
          <th>Name</th>
          <th>Kind</th>
          <th>Provisioning state</th>
          <th>Details</th>
        </tr>
      </thead>
      <tbody>{rows(tree, 0)}</tbody>
    </table>
  );
}
