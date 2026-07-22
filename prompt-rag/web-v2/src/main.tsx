import "@fontsource-variable/inter";
import "@fontsource-variable/noto-sans-sc";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import ManageApp from "./ManageApp";
import "./styles.css";

const RootApp = window.location.pathname === "/manage" ? ManageApp : App;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RootApp />
  </StrictMode>,
);
