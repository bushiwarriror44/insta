import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { Loader } from "./components/Loader";
import { useAuth } from "./context/AuthContext";
import { Accounts } from "./pages/Accounts";
import { Activity } from "./pages/Activity";
import { Dashboard } from "./pages/Dashboard";
import { Login } from "./pages/Login";
import { Publishing } from "./pages/Publishing";

export default function App() {
  const { state } = useAuth();

  if (state.state === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader label="Connecting to API..." />
      </div>
    );
  }

  if (state.state === "needs-login") {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
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
        <Route path="/activity" element={<Activity />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
