import { Navigate, Route, Routes } from "react-router-dom";
import { RefreshCw } from "lucide-react";

import { Layout } from "./components/Layout";
import { Loader } from "./components/Loader";
import { useAuth } from "./context/AuthContext";
import { Accounts } from "./pages/Accounts";
import { Activity } from "./pages/Activity";
import { Agent } from "./pages/Agent";
import { Calendar } from "./pages/Calendar";
import { Dashboard } from "./pages/Dashboard";
import { Login } from "./pages/Login";
import { Maintenance } from "./pages/Maintenance";
import { Operators } from "./pages/Operators";
import { Publishing } from "./pages/Publishing";
import { Renders } from "./pages/Renders";
import { Settings } from "./pages/Settings";

export default function App() {
  const { state, retryBootstrap } = useAuth();

  if (state.state === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader label="Подключение к API..." />
      </div>
    );
  }

  if (state.state === "error") {
    return (
      <div className="min-h-screen grid place-items-center px-4">
        <div className="card w-full max-w-md p-8 space-y-4 text-center">
          <h1 className="text-xl font-semibold">API недоступен</h1>
          <p className="text-sm text-slate-400 break-words">{state.message}</p>
          <button type="button" className="btn-primary w-full" onClick={retryBootstrap}>
            <RefreshCw size={16} />
            Повторить
          </button>
        </div>
      </div>
    );
  }

  if (state.state === "needs-login") {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Login />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="/accounts" element={<Accounts />} />
        <Route path="/publishing" element={<Publishing />} />
        <Route path="/upload" element={<Navigate to="/publishing" replace />} />
        <Route path="/agent" element={<Agent />} />
        <Route path="/renders" element={<Renders />} />
        <Route path="/calendar" element={<Calendar />} />
        <Route path="/activity" element={<Activity />} />
        <Route path="/maintenance" element={<Maintenance />} />
        <Route path="/operators" element={<Operators />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
