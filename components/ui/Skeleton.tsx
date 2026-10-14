export function Skeleton({h = 14, w}: {h?: number; w?: number | string}) {
  return <div className="ui-skel" style={{height: h, width: w}} aria-hidden="true"/>;
}
export function SkeletonRows({n = 4, h = 40}: {n?: number; h?: number}) {
  return <div className="ui-skel-stack" aria-busy="true" aria-label="Đang tải…">{Array.from({length: n}, (_, i) => <Skeleton key={i} h={h}/>)}</div>;
}
