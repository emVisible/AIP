import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router";
import { AppLayout } from "./components/layout/AppLayout";
import { Dashboard } from "./pages/Dashboard";
import { ComingSoon } from "./pages/ComingSoon";
const queryClient = new QueryClient({
    defaultOptions: {
        queries: { staleTime: 5_000, retry: 1 },
    },
});
/** 路由壳 + 全局 Provider（职责单一：只做装配）。 */
export function App() {
    return (_jsx(QueryClientProvider, { client: queryClient, children: _jsx(BrowserRouter, { children: _jsx(Routes, { children: _jsxs(Route, { element: _jsx(AppLayout, {}), children: [_jsx(Route, { index: true, element: _jsx(Dashboard, {}) }), _jsx(Route, { path: "designer", element: _jsx(ComingSoon, { title: "\u6D41\u7A0B\u8BBE\u8BA1\u5668" }) }), _jsx(Route, { path: "runs", element: _jsx(ComingSoon, { title: "\u8FD0\u884C\u5386\u53F2" }) }), _jsx(Route, { path: "hitl", element: _jsx(ComingSoon, { title: "\u5BA1\u6279\u4E2D\u5FC3" }) }), _jsx(Route, { path: "settings", element: _jsx(ComingSoon, { title: "\u8BBE\u7F6E" }) }), _jsx(Route, { path: "*", element: _jsx(ComingSoon, { title: "404" }) })] }) }) }) }));
}
