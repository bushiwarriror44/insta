import React from "react";
import ReactDOM from "react-dom/client";

import { GateRoot } from "./components/GateRoot";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <GateRoot />
  </React.StrictMode>
);
