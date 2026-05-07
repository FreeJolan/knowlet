import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App.tsx";
import { syncLanguageFromBackend } from "./i18n";
import "./i18n"; // side-effect: initializes i18next before any component renders
import { bootThemeManager } from "./lib/theme";
import "./styles/globals.css";

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("missing #root in index.html");

// Fire-and-forget: backend language wins once /api/health responds.
void syncLanguageFromBackend();

// Apply persisted theme + start watching system preference.
bootThemeManager();

createRoot(rootEl).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
