/** 占位页（M-B/M-C 逐个替换为实现）。职责单一：仅呈现。 */
export function ComingSoon({ title }: { title: string }) {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center space-y-2">
        <h1 className="text-xl font-bold">{title}</h1>
        <p className="text-sm text-slate-400">即将上线 —— 详见路线图</p>
      </div>
    </div>
  );
}
