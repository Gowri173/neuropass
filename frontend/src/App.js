import React, { useEffect, useState } from "react";
import {
  BrowserRouter as Router,
  Routes,
  Route,
  useNavigate,
} from "react-router-dom";

import AuthFlow from "./AuthFlow";
import BankingDashboard from "./BankingDashboard";

/* ---------- Protected Route Wrapper ---------- */

function ProtectedRoute() {
  const navigate = useNavigate();
  const [isChecking, setIsChecking] = useState(true);

  useEffect(() => {
    const user = localStorage.getItem("neuropass_user");

    // 🧠 Prevent double navigation in React StrictMode
    const hasRedirected = sessionStorage.getItem("protected_redirected");

    if (!user && !hasRedirected) {
      sessionStorage.setItem("protected_redirected", "true");
      navigate("/", { replace: true });
    }

    setIsChecking(false);
  }, [navigate]);

  if (isChecking) return null;

  return <BankingDashboard />;
}

/* ---------- App Router ---------- */

export default function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<AuthFlow />} />
        <Route path="/dashboard" element={<ProtectedRoute />} />
      </Routes>
    </Router>
  );
}
