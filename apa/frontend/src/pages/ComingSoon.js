import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/** 占位页（M-B/M-C 逐个替换为实现）。职责单一：仅呈现。 */
export function ComingSoon({ title }) {
    return (_jsx("div", { className: "flex items-center justify-center h-full", children: _jsxs("div", { className: "text-center space-y-2", children: [_jsx("h1", { className: "text-xl font-bold", children: title }), _jsx("p", { className: "text-sm text-slate-400", children: "\u5373\u5C06\u4E0A\u7EBF \u2014\u2014 \u8BE6\u89C1\u8DEF\u7EBF\u56FE" })] }) }));
}
