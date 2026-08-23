import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router";
import { AppLayout } from "./components/layout/AppLayout";
import { Dashboard } from "./pages/Dashboard";
import { DesignerPage } from "./pages/designer/DesignerPage";
import { Runs } from "./pages/Runs";
import { Hitl } from "./pages/Hitl";
import { Assistant } from "./pages/Assistant";
import { Settings } from "./pages/Settings";
import { ComingSoon } from "./pages/ComingSoon";
const queryClient = new QueryClient({
    defaultOptions: {
        queries: { staleTime: 5_000, retry: 1 },
    },
});
/** 路由壳 + 全局 Provider（职责单一：只做装配）。 */
export function App() {
    return (_jsx(QueryClientProvider, { client: queryClient, children: _jsx(BrowserRouter, { children: _jsx(Routes, { children: _jsxs(Route, { element: _jsx(AppLayout, {}), children: [_jsx(Route, { index: true, element: _jsx(Dashboard, {}) }), _jsx(Route, { path: "designer", element: _jsx(DesignerPage, {}) }), _jsx(Route, { path: "runs", element: _jsx(Runs, {}) }), _jsx(Route, { path: "hitl", element: _jsx(Hitl, {}) }), _jsx(Route, { path: "settings", element: _jsx(Settings, {}) }), _jsx(Route, { path: "ai", element: _jsx(Assistant, {}) }), _jsx(Route, { path: "*", element: _jsx(ComingSoon, { title: "404" }) })] }) }) }) }));
}
