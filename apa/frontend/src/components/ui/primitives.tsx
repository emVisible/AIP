import { cn } from "../../lib/utils";

type Variant = "default" | "primary" | "ghost";

const VARIANTS: Record<Variant, string> = {
  default: "bg-white hover:bg-slate-50 text-slate-700 border-slate-300",
  primary: "bg-brand hover:bg-blue-700 text-white border-brand",
  ghost: "bg-transparent hover:bg-slate-100 text-slate-600 border-transparent",
};

export function Badge({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
        tone,
      )}
    >
      {children}
    </span>
  );
}

export function Button({
  variant = "default",
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button className={cn(VARIANTS[variant], "rounded-lg transition-colors", className)}
            {...props} />
  );
}

export function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-xl border border-slate-200 bg-surface shadow-sm", className)}>
      {children}
    </div>
  );
}

export function CardHeader({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="border-b border-slate-100 px-5 py-3">
      <h3 className="text-sm font-semibold">{title}</h3>
      {sub && <p className="text-xs text-slate-400 mt-0.5">{sub}</p>}
    </div>
  );
}
