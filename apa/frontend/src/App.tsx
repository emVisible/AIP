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
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<Dashboard />} />
            <Route path="designer" element={<DesignerPage />} />
            <Route path="runs" element={<Runs />} />
            <Route path="hitl" element={<Hitl />} />
            <Route path="settings" element={<Settings />} />
            <Route path="ai" element={<Assistant />} />
            <Route path="*" element={<ComingSoon title="404" />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
