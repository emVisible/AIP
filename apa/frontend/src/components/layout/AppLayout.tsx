import { NavLink, Outlet } from "react-router";
import {
  Activity,
  Bot,
  CircleCheck,
  Cpu,
  Hand,
  Settings,
} from "lucide-react";

const NAV = [
  { to: "/", label: "监控", icon: Activity, end: true },
  { to: "/designer", label: "设计器", icon: Bot },
  { to: "/runs", label: "运行", icon: CircleCheck },
  { to: "/hitl", label: "审批", icon: Hand },
  { to: "/settings", label: "设置", icon: Settings },
];

/** 应用布局壳：Sidebar + 主内容 Outlet + Statusbar（职责单一：仅布局）。 */
export function AppLayout() {
  return (
    <div className="flex h-full">
      <aside className="w-56 shrink-0 bg-sidebar text-sidebar-fg flex flex-col">
        <div className="px-5 py-4 border-b border-sidebar-accent">
          <span className="text-lg font-bold tracking-wide">APA</span>
          <span className="text-[10px] text-slate-500 block leading-none mt-0.5">
            Agentic Process Automation
          </span>
        </div>
        <nav className="flex-1 py-3">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-5 py-2.5 text-sm transition-colors ${
                  isActive
                    ? "bg-sidebar-accent text-white border-r-2 border-brand"
                    : "hover:bg-sidebar-accent/60"
                }`
              }
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="px-5 py-3 text-[11px] text-slate-600 border-t border-sidebar-accent">
          v0.5 · poc
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
        <footer className="border-t border-slate-200 px-4 py-1.5 text-xs
                           text-slate-400 bg-white flex justify-between">
          <span>APA Studio</span>
          <Cpu size={12} />
        </footer>
      </div>
    </div>
  );
}
