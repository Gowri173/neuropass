// ✅ src/Login.js — FINAL FIXED VERSION (guaranteed session_id sync)

import React, { useRef, useState } from "react";
import styled, { keyframes } from "styled-components";
import { useNavigate } from "react-router-dom";
import useBehaviorCapture from "./useBehaviorCapture";
import useMouseBehavior from "./useMouseBehavior";

/* ---------- Styles ---------- */

const fadeIn = keyframes`
  from {
    opacity: 0;
    transform: translateY(15px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
`;

const Container = styled.div`
  min-height: 100vh;
  background: radial-gradient(circle at top left, #0a0f1e, #05070b);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: ${fadeIn} 0.8s ease forwards;
`;

const Card = styled.div`
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(15px);
  border-radius: 20px;
  padding: 2rem;
  width: 380px;
  text-align: center;
  box-shadow: 0 0 25px rgba(0, 200, 255, 0.12);
`;

const Title = styled.h1`
  color: #00b7ff;
  margin-bottom: 1.2rem;
`;

const Input = styled.input`
  width: 100%;
  padding: 12px;
  margin-bottom: 12px;
  border-radius: 10px;
  border: none;
  background: #10131a;
  color: #e6edf3;

  &:focus {
    outline: 2px solid #00b7ff;
  }
`;

const Button = styled.button`
  width: 100%;
  padding: 12px;
  border-radius: 10px;
  border: none;
  background: linear-gradient(90deg, #007aff, #00d4ff);
  color: white;
  font-weight: 600;
  cursor: pointer;
  transition: 0.3s;

  &:hover {
    transform: scale(1.03);
    box-shadow: 0 0 15px #00b7ff66;
  }

  &:disabled {
    background: #444;
    cursor: not-allowed;
  }
`;

const Message = styled.pre`
  margin-top: 12px;
  color: ${({ $success }) => ($success ? "#00ffb7" : "#ff4d4f")};
  white-space: pre-wrap;
  font-weight: 600;
`;

/* ---------- Component ---------- */

export default function Login({ onSuccess }) {
  const [userId, setUserId] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const navigate = useNavigate();
  const sessionStartedRef = useRef(false);

  /** ----------------------
   * BEHAVIOR CAPTURE HOOKS
   * -------------------- */
  const {
    getSessionId,
    sessionId, // <-- LIVE session
    flush: flushKeys,
    newSession,
  } = useBehaviorCapture(userId);

  const { flushMouseData } = useMouseBehavior(userId);

  const API_BASE =
    process.env.REACT_APP_API_BASE || "http://localhost:8000";

  /** ----------------------
   * Start NEW session when typing password
   * -------------------- */
  const handlePasswordSessionStart = () => {
    if (!sessionStartedRef.current) {
      const newId = newSession(); // create new typing session
      console.log("🔄 NEW LOGIN SESSION:", newId);
      sessionStartedRef.current = true;
    }
  };

  /** ----------------------
   * LOGIN
   * -------------------- */
  const handleLogin = async () => {
    if (!userId || !password) return;

    setLoading(true);
    setMessage("");

    try {
      await flushKeys();
      await flushMouseData();

      const loginSessionId = sessionId;
      console.log("🔑 Using session_id =", loginSessionId);

      if (!loginSessionId) {
        setMessage(
          "❌ Missing session_id. Please type your password to begin capturing behavior."
        );
        setLoading(false);
        return;
      }

      const payload = {
        user_id: userId,
        password,
        session_id: loginSessionId,
      };

      console.log("📤 Sending Login Payload:", payload);

      const res = await fetch(`${API_BASE}/api/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      console.log("📥 Login Response:", data);

      if (data.decision === "accept") {
        setMessage(
          `✅ Access Granted! (Confidence: ${(data.score * 100).toFixed(
            1
          )}%)`
        );

        localStorage.setItem("neuropass_user", userId);
        localStorage.setItem("authScore", data.score);

        // async model update
        fetch(`${API_BASE}/api/update_model`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_id: userId,
            session_id: loginSessionId,
          }),
        }).catch((e) => console.warn("Model update failed:", e));

        if (onSuccess) onSuccess(userId);
        navigate("/dashboard");
      } else {
        setMessage(
          `❌ Access Denied (Confidence: ${(data.score * 100).toFixed(
            1
          )}%)\nReason: ${data.reason}`
        );
      }
    } catch (err) {
      console.error("❌ Login Error:", err);
      setMessage(`❌ Login failed: ${err.message}`);
    }

    setLoading(false);
  };

  /** ----------------------
   * ENTER to Login
   * -------------------- */
  const handleKeyPress = (e) => {
    if (e.key === "Enter" && !loading && userId && password) {
      handleLogin();
    }
  };

  return (
    <Container>
      <Card>
        <Title>🧠 NeuroPass Login</Title>

        <Input
          placeholder="User ID"
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          onKeyDown={handleKeyPress}
        />

        <Input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value);
            handlePasswordSessionStart();
          }}
          onKeyDown={(e) => {
            handlePasswordSessionStart();
            handleKeyPress(e);
          }}
        />

        <Button
          onClick={handleLogin}
          disabled={!userId || !password || loading}
        >
          {loading ? "Verifying..." : "Login"}
        </Button>

        {message && (
          <Message $success={message.startsWith("✅")}>
            {message}
          </Message>
        )}
      </Card>
    </Container>
  );
}
