// ✅ src/AuthFlow.js — Final Stable Version (with redirect fix)

import React, { useState, useEffect } from "react";
import styled, { keyframes } from "styled-components";
import { motion, AnimatePresence } from "framer-motion";
import useBehaviorCapture from "./useBehaviorCapture";
import useMouseBehavior from "./useMouseBehavior";
import { useNavigate } from "react-router-dom";

/* ---------- Global Styles ---------- */

const gradient = "linear-gradient(135deg, #00b7ff, #00ffb7)";

const fadeUp = keyframes`
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
`;

const Page = styled.div`
  min-height: 100vh;
  background: radial-gradient(circle at top left, #05070b, #0a0f1e);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem;
  overflow: hidden;
`;

const Card = styled(motion.div)`
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 20px;
  padding: 2rem;
  width: 100%;
  max-width: 440px;
  text-align: center;
  box-shadow: 0 0 30px rgba(0, 200, 255, 0.1);
  backdrop-filter: blur(15px);
  animation: ${fadeUp} 0.8s ease;
`;

const Title = styled.h1`
  color: #00ffb7;
  font-size: clamp(1.6rem, 4vw, 2rem);
  margin-bottom: 0.8rem;
`;

const Subtitle = styled.p`
  color: #cbd5e1;
  font-size: 0.95rem;
  margin-bottom: 1.5rem;
`;

const Input = styled.input`
  width: 100%;
  padding: 12px 14px;
  margin-bottom: 15px;
  border-radius: 10px;
  border: 1px solid #1e293b;
  background: #0f172a;
  color: #e6edf3;
  font-size: 15px;
  transition: 0.3s;

  &:focus {
    outline: none;
    border-color: #00ffb7;
    box-shadow: 0 0 0 3px rgba(0, 255, 183, 0.15);
  }
`;

const Button = styled.button`
  width: 100%;
  padding: 12px;
  border: none;
  border-radius: 12px;
  background: ${gradient};
  color: white;
  font-weight: 600;
  cursor: pointer;
  margin-top: 10px;
  transition: all 0.25s ease;

  &:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 20px rgba(0, 255, 183, 0.25);
  }

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
`;

const Message = styled(motion.pre)`
  margin-top: 1rem;
  color: ${({ $success }) => ($success ? "#00ffb7" : "#ff4d4f")};
  white-space: pre-wrap;
  font-weight: 600;
`;

const Counter = styled.p`
  color: #aaa;
  font-size: 0.9rem;
  margin-top: 6px;
`;

const SwitchAuth = styled.p`
  margin-top: 1rem;
  color: #ccc;
  font-size: 0.9rem;

  span {
    color: #00b7ff;
    cursor: pointer;
    text-decoration: underline;
    font-weight: 600;
  }
`;

/* ---------- Component ---------- */

export default function AuthFlow() {
    const [phase, setPhase] = useState("register");
    const [user, setUser] = useState("");
    const [pass, setPass] = useState("");
    const [msg, setMsg] = useState("");
    const [loading, setLoading] = useState(false);

    const [samples, setSamples] = useState(0);
    const [keystrokes, setKeystrokes] = useState(0);
    const [mouseMoves, setMouseMoves] = useState(0);

    const [enableMouse, setEnableMouse] = useState(true);

    const navigate = useNavigate();

    const { flush, sessionId, newSession } = useBehaviorCapture(user);
    const {
        flushMouseData,
        newSession: syncMouseSession,
        stopTracking,
    } = useMouseBehavior(enableMouse ? user : null, sessionId);

    /* ---------- Prevent infinite redirect loop ---------- */
    useEffect(() => {
        const loggedIn = localStorage.getItem("neuropass_user");
        const hasRedirected = sessionStorage.getItem("auth_redirected");

        if (loggedIn && !hasRedirected) {
            sessionStorage.setItem("auth_redirected", "true");
            navigate("/dashboard", { replace: true });
        }
    }, [navigate]);

    /* ---------- Training data tracking ---------- */
    useEffect(() => {
        if (!pass || phase !== "train") return;

        const onKey = () => setKeystrokes((k) => k + 1);
        const onMove = () => setMouseMoves((m) => m + 1);

        window.addEventListener("keydown", onKey);
        window.addEventListener("mousemove", onMove);

        return () => {
            window.removeEventListener("keydown", onKey);
            window.removeEventListener("mousemove", onMove);
        };
    }, [pass, phase]);

    /* ---------- Register ---------- */
    const handleRegister = async () => {
        setLoading(true);
        setMsg("");

        try {
            const res = await fetch("http://localhost:8000/api/register", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ user_id: user, password: pass }),
            });

            const data = await res.json();

            if (data.status === "ok") {
                setMsg("✅ Registered successfully! Begin training your model.");
                setPhase("train");
                setPass("");
            } else setMsg("❌ " + data.message);
        } catch (err) {
            setMsg(`❌ ${err.message}`);
        } finally {
            setLoading(false);
        }
    };

    /* ---------- Save behavioral sample ---------- */
    const handleSaveSample = async () => {
        if (!user || !pass) return;

        setMsg("Saving behavioral sample...");

        try {
            await flush();
            await flushMouseData();

            setSamples((prev) => {
                const newCount = prev + 1;

                if (newCount >= 10) {
                    stopTracking();
                    setEnableMouse(false);
                    setMsg("✅ 10 samples collected — ready to train your model.");
                } else {
                    setMsg(`✅ Sample ${newCount} saved.`);
                }

                return newCount;
            });

            setPass("");
            setKeystrokes(0);
            setMouseMoves(0);

            const newId = newSession();
            syncMouseSession(newId);
        } catch (err) {
            setMsg(`❌ Failed to save sample: ${err.message}`);
        }
    };

    /* ---------- Train Model ---------- */
    const handleTraining = async () => {
        setLoading(true);
        setMsg("🚀 Training your model...");

        try {
            const res = await fetch("http://localhost:8000/api/train_user", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ user_id: user }),
            });

            const data = await res.json();

            if (data.status === "ok") {
                setMsg("✅ Model trained successfully! You can now log in.");
                setPhase("login");
                setPass("");
                setSamples(0);
            } else setMsg("❌ " + data.message);
        } catch (err) {
            setMsg(`❌ ${err.message}`);
        } finally {
            setLoading(false);
        }
    };

    /* ---------- Login ---------- */
    const handleLogin = async () => {
        setLoading(true);
        setMsg("");

        try {
            await flush();
            await flushMouseData();

            const res = await fetch("http://localhost:8000/api/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    user_id: user,
                    password: pass,
                    session_id: sessionId,
                }),
            });

            const data = await res.json();

            if (data.decision === "accept") {
                setMsg(
                    `✅ Access Granted! Confidence ${(data.score * 100).toFixed(1)}%`
                );

                localStorage.setItem("neuropass_user", user);
                sessionStorage.removeItem("auth_redirected");

                navigate("/dashboard", { replace: true });
            } else {
                setMsg(`❌ Access Denied: ${data.reason}`);
            }
        } catch (err) {
            setMsg(`❌ ${err.message}`);
        } finally {
            setLoading(false);
        }
    };

    /* ---------- Render ---------- */
    return (
        <Page>
            <AnimatePresence mode="wait">
                {/* -------- REGISTER -------- */}
                {phase === "register" && (
                    <Card
                        key="register"
                        initial={{ opacity: 0, y: 30 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -30 }}
                        transition={{ duration: 0.4 }}
                    >
                        <Title>🧠 Create Account</Title>
                        <Subtitle>Register your NeuroPass profile.</Subtitle>

                        <Input
                            placeholder="User ID"
                            value={user}
                            onChange={(e) => setUser(e.target.value)}
                        />

                        <Input
                            type="password"
                            placeholder="Password"
                            value={pass}
                            onChange={(e) => setPass(e.target.value)}
                        />

                        <Button
                            onClick={handleRegister}
                            disabled={!user || !pass || loading}
                        >
                            {loading ? "Registering..." : "Register"}
                        </Button>

                        {msg && <Message $success={msg.startsWith("✅")}>{msg}</Message>}

                        <SwitchAuth>
                            Already have an account?{" "}
                            <span onClick={() => setPhase("login")}>Login</span>
                        </SwitchAuth>
                    </Card>
                )}

                {/* -------- TRAIN -------- */}
                {phase === "train" && (
                    <Card
                        key="train"
                        initial={{ opacity: 0, y: 30 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -30 }}
                    >
                        <Title>🎯 Train Behavioral Model</Title>
                        <Subtitle>Type naturally and move your mouse as usual.</Subtitle>

                        <Input
                            type="password"
                            placeholder="Type password sample"
                            value={pass}
                            onChange={(e) => setPass(e.target.value)}
                        />

                        <Counter>Samples: {samples} / 10</Counter>
                        <Counter>
                            ⌨ Keystrokes: {keystrokes} • 🖱 Moves: {mouseMoves}
                        </Counter>

                        <Button
                            onClick={handleSaveSample}
                            disabled={!user || !pass || samples >= 10}
                        >
                            {samples < 10
                                ? `Save Sample (${samples}/10)`
                                : "Samples Complete ✅"}
                        </Button>

                        <Button
                            onClick={handleTraining}
                            disabled={samples < 10 || loading}
                        >
                            {loading ? "Training..." : "🚀 Train My Model"}
                        </Button>

                        {msg && (
                            <Message $success={msg.startsWith("✅")}>{msg}</Message>
                        )}
                    </Card>
                )}

                {/* -------- LOGIN -------- */}
                {phase === "login" && (
                    <Card
                        key="login"
                        initial={{ opacity: 0, y: 30 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -30 }}
                    >
                        <Title>🔐 Login</Title>
                        <Subtitle>Enter your credentials to verify your identity.</Subtitle>

                        <Input
                            placeholder="User ID"
                            value={user}
                            onChange={(e) => setUser(e.target.value)}
                        />

                        <Input
                            type="password"
                            placeholder="Password"
                            value={pass}
                            onChange={(e) => setPass(e.target.value)}
                        />

                        <Button
                            onClick={handleLogin}
                            disabled={!user || !pass || loading}
                        >
                            {loading ? "Verifying..." : "Login"}
                        </Button>

                        {msg && (
                            <Message $success={msg.startsWith("✅")}>{msg}</Message>
                        )}
                    </Card>
                )}
            </AnimatePresence>
        </Page>
    );
}
