import { jsx as _jsx } from "react/jsx-runtime";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// thin bootstrap（对齐 dsh apps/web/main.ts 模式：入口只找挂载点与装配）
import { App } from "./App";
import "./index.css";
const el = document.getElementById("root");
if (!el)
    throw new Error("frontend: missing #root");
createRoot(el).render(_jsx(StrictMode, { children: _jsx(App, {}) }));
