import React from "react";
import ReactDOM from "react-dom/client";
import "./i18n";
import "./index.css";
import { App } from "./App";
import { AppProvider } from "./context/AppContext";
import { ToastProvider } from "./components/ui";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AppProvider>
      <ToastProvider>
        <App />
      </ToastProvider>
    </AppProvider>
  </React.StrictMode>
);
