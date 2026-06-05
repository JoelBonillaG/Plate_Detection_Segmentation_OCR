import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { RealtimeProvider } from "./context/RealtimeContext.jsx";
import "./styles/app.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <RealtimeProvider>
      <App />
    </RealtimeProvider>
  </React.StrictMode>
);
