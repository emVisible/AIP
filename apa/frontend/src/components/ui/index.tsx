/**
 * APA UI 组件集 —— 轻量、零依赖、可复用的基础控件。
 *
 * 设计令牌（index.css @theme）：
 *   主色 zinc-900（深灰主按钮，Linear/Vercel 风格）
 *   语义色 slate 边框 / emerald·amber·red 状态色
 *   字号层级 text-[11px] / text-xs / text-sm
 *
 * 原则：
 *   - 每个组件只对「用户交互」负责（第三部 2.1）
 *   - variant 用查表而非条件拼接（显式优于隐式）
 *   - focus-visible 统一 ring，键盘可达
 */
import { useEffect } from "react";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...parts: Array<string | false | null | undefined>) {
  return twMerge(clsx(parts));
}

// ---- Button ---------------------------------------------------------------

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md";

const BTN_VARIANT: Record<ButtonVariant, string> = {
  primary:
    "bg-zinc-900 text-white hover:bg-zinc-700 disabled:hover:bg-zinc-900",
  secondary:
    "bg-white text-slate-700 border border-slate-200 hover:bg-slate-50",
  ghost: "text-slate-600 hover:bg-slate-100",
  danger:
    "bg-white text-red-600 border border-red-200 hover:bg-red-50",
};
const BTN_SIZE: Record<ButtonSize, string> = {
  sm: "h-7 px-2.5 text-xs gap-1",
  md: "h-8 px-3 text-xs gap-1.5",
};

export function Button({
  variant = "secondary",
  size = "md",
  className,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
}) {
  return (
    <button
      {...rest}
      className={cn(
        "inline-flex items-center justify-center rounded-md font-medium",
        "transition-colors select-none",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40",
        "disabled:opacity-50 disabled:pointer-events-none",
        BTN_VARIANT[variant],
        BTN_SIZE[size],
        className,
      )}
    />
  );
}

export function IconButton({
  label,
  className,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      {...rest}
      title={label}
      aria-label={label}
      className={cn(
        "inline-flex items-center justify-center w-7 h-7 rounded-md",
        "text-slate-500 hover:text-slate-800 hover:bg-slate-100",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40",
        className,
      )}
    />
  );
}

// ---- Inputs -----------------------------------------------------------------

const FIELD_BASE =
  "bg-white border border-slate-200 rounded-md text-xs text-slate-800 " +
  "placeholder:text-slate-300 " +
  "focus:outline-none focus:border-slate-400 focus:ring-2 focus:ring-blue-500/20 " +
  "disabled:opacity-50";

export function Input({
  className,
  ...rest
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...rest} className={cn(FIELD_BASE, "h-8 px-2.5", className)} />;
}

export function Textarea({
  className,
  ...rest
}: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...rest}
      className={cn(FIELD_BASE, "px-2.5 py-2 leading-relaxed", className)}
    />
  );
}

export function Select({
  className,
  children,
  ...rest
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...rest} className={cn(FIELD_BASE, "h-8 px-2", className)}>
      {children}
    </select>
  );
}

export function Field({ label, hint, children }: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1">
      <span className="flex items-baseline gap-2">
        <span className="text-xs font-medium text-slate-600">{label}</span>
        {hint && <span className="text-[10px] text-slate-400">{hint}</span>}
      </span>
      {children}
    </label>
  );
}

// ---- Badge ------------------------------------------------------------------

type BadgeTone = "neutral" | "blue" | "green" | "amber" | "red" | "violet";

const BADGE_TONE: Record<BadgeTone, string> = {
  neutral: "bg-slate-100 text-slate-500",
  blue: "bg-blue-50 text-blue-600",
  green: "bg-emerald-50 text-emerald-600",
  amber: "bg-amber-50 text-amber-600",
  red: "bg-red-50 text-red-600",
  violet: "bg-violet-50 text-violet-600",
};

export function Badge({
  tone = "neutral",
  className,
  ...rest
}: React.HTMLAttributes<HTMLSpanElement> & { tone?: BadgeTone }) {
  return (
    <span
      {...rest}
      className={cn(
        "inline-flex items-center rounded px-1.5 py-px text-[10px]",
        "font-medium leading-4 whitespace-nowrap",
        BADGE_TONE[tone],
        className,
      )}
    />
  );
}

/** 风险等级 → 色调映射（registry L0–L3）。 */
export function riskTone(risk: string): BadgeTone {
  if (risk.startsWith("L0")) return "green";
  if (risk.startsWith("L1")) return "blue";
  if (risk.startsWith("L2")) return "amber";
  return "red";
}

// ---- Card -------------------------------------------------------------------

export function Card({
  className,
  ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      {...rest}
      className={cn(
        "bg-white border border-slate-200 rounded-lg",
        className,
      )}
    />
  );
}

export function CardHeader({
  title,
  right,
  className,
}: {
  title: React.ReactNode;
  right?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn(
      "flex items-center justify-between px-3 py-2 border-b border-slate-100",
      className,
    )}>
      <span className="text-xs font-semibold text-slate-700">{title}</span>
      {right}
    </div>
  );
}

// ---- Dialog ------------------------------------------------------------------

export function Dialog({
  open,
  onClose,
  width = 560,
  children,
}: {
  open: boolean;
  onClose: () => void;
  /** 最大宽度像素 */
  width?: number;
  children: React.ReactNode;
}) {
  useEscapeClose(open, onClose);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center
                    bg-black/30 pt-[8vh]"
         onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div role="dialog" aria-modal="true"
           style={{ maxWidth: width }}
           className="w-full mx-4 bg-white rounded-xl shadow-2xl
                      border border-slate-200 overflow-hidden">
        {children}
      </div>
    </div>
  );
}

/** ESC 关闭；open 变化时重绑。 */
function useEscapeClose(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
}

// ---- Drawer（底部抽屉）-------------------------------------------------------

export function Drawer({
  open,
  onClose,
  height = 260,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  height?: number;
  title: React.ReactNode;
  children: React.ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="absolute inset-x-0 bottom-0 z-30 border-t border-slate-200
                    bg-white shadow-[0_-4px_16px_rgba(0,0,0,0.06)]"
         style={{ height }}>
      <div className="flex items-center justify-between px-3 py-1.5
                      border-b border-slate-100">
        <span className="text-xs font-semibold text-slate-700">{title}</span>
        <IconButton label="关闭" onClick={onClose}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </IconButton>
      </div>
      <div className="overflow-y-auto" style={{ height: height - 37 }}>
        {children}
      </div>
    </div>
  );
}
