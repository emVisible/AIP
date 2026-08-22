import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { cn } from "../../lib/utils";
const VARIANTS = {
    default: "bg-white hover:bg-slate-50 text-slate-700 border-slate-300",
    primary: "bg-brand hover:bg-blue-700 text-white border-brand",
    ghost: "bg-transparent hover:bg-slate-100 text-slate-600 border-transparent",
};
export function Badge({ children, tone, }) {
    return (_jsx("span", { className: cn("inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium", tone), children: children }));
}
export function Button({ variant = "default", className, ...props }) {
    return (_jsx("button", { className: cn(VARIANTS[variant], "rounded-lg transition-colors", className), ...props }));
}
export function Card({ children, className }) {
    return (_jsx("div", { className: cn("rounded-xl border border-slate-200 bg-surface shadow-sm", className), children: children }));
}
export function CardHeader({ title, sub }) {
    return (_jsxs("div", { className: "border-b border-slate-100 px-5 py-3", children: [_jsx("h3", { className: "text-sm font-semibold", children: title }), sub && _jsx("p", { className: "text-xs text-slate-400 mt-0.5", children: sub })] }));
}
