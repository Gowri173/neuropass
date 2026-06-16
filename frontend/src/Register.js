// ✅ src/Register.js — updated so tracking starts only when typing begins

import React, { useState, useEffect } from "react";
import styled from "styled-components";

import useBehaviorCapture from "./useBehaviorCapture";
import useMouseBehavior from "./useMouseBehavior";

/* ---------- Styling ---------- */

const Container = styled.div`
  min-height: 100vh;
  background: radial-gradient(circle at bottom right, #0a0f1e, #05070b);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  gap: 2.5rem;
  flex-wrap: wrap;
  padding: 2rem;
`;

const Card = styled.div`
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(15px);
  border-radius: 20px;
  padding: 2rem;
  width: 420px;
  text-align: center;
  box-shadow: 0 0 25px rgba(0, 200, 255, 0.12);
`;

const Title = styled.h1`
  color: #00ffb7;
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
    outline: 2px solid #00ffb7;
  }
`;

const Button = styled.button`
  width: 100%;
  padding: 12px;
  border-radius: 10px;
  border: none;
  background: linear-gradient(90deg, #00ffb7, #00b7ff);
  color: white;
  font-weight: 600;
  cursor: pointer;
  margin-top: 8px;
  transition: 0.3s;

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

const Counter = styled.p`
  color: #aaa;
  font-size: 0.9rem;
  margin-top: 6px;
`;

/* ---------- Component ---------- */

export default function Register() {
    const [phase, setPhase] = useState("register"); // register → train → done

    const [regUser, setRegUser] = useState("");
    const [regPass, setRegPass] = useState("");
    const [regMsg, setRegMsg] = useState("");
    const [regLoading, setRegLoading] = useState(false);

    const [samples, setSamples] = useState(0);
    const [keystrokes, setKeystrokes] = useState(0);
    const [mouseMoves, setMouseMoves] = useState(0);

    const [trainMsg, setTrainMsg] = useState("");
    const [trainLoading, setTrainLoading] = useState(false);

    // Tracking toggles
    const [trackingActive, setTrackingActive] = useState(false);
    const [enableMouse, setEnableMouse] = useState(false);

    const { flush, sessionId, newSession } = useBehaviorCapture(
        trackingActive ? regUser : null
    );

    const {
        flushMouseData,
        newSession: syncMouseSession,
        stopTracking,
    } = useMouseBehavior(enableMouse ? regUser : null, sessionId);

    /* ---------- Start tracking only when user begins typing ---------- */
    useEffect(() => {
        if (phase === "train" && regPass && !trackingActive) {
            setTrackingActive(true);
            setEnableMouse(true);
            setTrainMsg("🎯 Tracking started — continue typing your sample.");
        }
    }, [regPass, trackingActive, phase]);

    /* ---------- Keystroke counter ---------- */
    useEffect(() => {
        if (!trackingActive) return;

        const onKey = () => setKeystrokes((k) => k + 1);
        window.addEventListener("keydown", onKey);

        return () => window.removeEventListener("keydown", onKey);
    }, [trackingActive]);

    /* ---------- Mouse movement counter ---------- */
    useEffect(() => {
        if (!trackingActive || !enableMouse) return;

        const onMove = () => setMouseMoves((m) => m + 1);
        window.addEventListener("mousemove", onMove);

        return () => window.removeEventListener("mousemove", onMove);
    }, [trackingActive, enableMouse]);

    /* ---------- Register ---------- */
    const handleRegister = async () => {
        setRegLoading(true);
        setRegMsg("");

        try {
            const res = await fetch("http://localhost:8000/api/register", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    user_id: regUser,
                    password: regPass,
                }),
            });

            const data = await res.json();

            if (data.status === "ok") {
                setRegMsg("✅ Registration successful. Now train your behavioral model.");
                setPhase("train");
                setRegPass("");
                setTrackingActive(false);
                setEnableMouse(false);
            } else {
                setRegMsg(`❌ ${data.message}`);
            }
        } catch (err) {
            setRegMsg(`❌ Registration error: ${err.message || err}`);
        } finally {
            setRegLoading(false);
        }
    };

    /* ---------- Save Sample ---------- */
    const handleSaveSample = async () => {
        if (!regUser || !trackingActive) return;

        setTrainMsg("Saving behavioral sample...");

        try {
            await flush();
            await flushMouseData();

            setSamples((prev) => {
                const newCount = prev + 1;

                if (newCount >= 10) {
                    stopTracking();
                    setEnableMouse(false);
                    setTrackingActive(false);
                    setTrainMsg("✅ 10 samples collected — ready to train model.");
                } else {
                    setTrainMsg(`✅ Saved sample ${newCount}. Keep going!`);
                }

                return newCount;
            });

            // Reset for next sample
            setRegPass("");
            setKeystrokes(0);
            setMouseMoves(0);
            setTrackingActive(false);
            setEnableMouse(false);

            const newId = newSession();
            syncMouseSession(newId);
        } catch (err) {
            setTrainMsg(`❌ Failed to save sample: ${err.message || err}`);
        }
    };

    /* ---------- Train Model ---------- */
    const handleTraining = async () => {
        setTrainLoading(true);
        setTrainMsg("🚀 Training your model...");

        try {
            const res = await fetch("http://localhost:8000/api/train_user", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ user_id: regUser }),
            });

            const data = await res.json();

            if (data.status === "ok") {
                setTrainMsg("✅ Model trained successfully! You can now log in.");
                setPhase("done");

                setSamples(0);
                setKeystrokes(0);
                setMouseMoves(0);
                setTrackingActive(false);
                setEnableMouse(false);
                setRegUser("");
                setRegPass("");
            } else {
                setTrainMsg(`❌ ${data.message}`);
            }
        } catch (err) {
            setTrainMsg(`❌ Training failed: ${err.message || err}`);
        } finally {
            setTrainLoading(false);
        }
    };

    /* ---------- UI ---------- */

    return (
        <Container>
            {phase === "register" && (
                <Card>
                    <Title>🧠 Create Account</Title>

                    <Input
                        placeholder="User ID"
                        value={regUser}
                        onChange={(e) => setRegUser(e.target.value)}
                    />

                    <Input
                        type="password"
                        placeholder="Password"
                        value={regPass}
                        onChange={(e) => setRegPass(e.target.value)}
                    />

                    <Button onClick={handleRegister} disabled={!regUser || !regPass || regLoading}>
                        {regLoading ? "Registering..." : "Register"}
                    </Button>

                    {regMsg && (
                        <Message $success={regMsg.startsWith("✅")}>{regMsg}</Message>
                    )}
                </Card>
            )}

            {phase === "train" && (
                <Card>
                    <Title>🎯 Train Behavioral Model</Title>

                    <p style={{ color: "#cbd5e1", fontSize: "0.9rem" }}>
                        Start typing your password to begin capturing.
                        Move your mouse naturally.
                        Save 10 samples before training your model.
                    </p>

                    <Input
                        type="password"
                        placeholder="Type Password Sample"
                        value={regPass}
                        onChange={(e) => setRegPass(e.target.value)}
                    />

                    <Counter>Samples saved: {samples} / 10</Counter>
                    <Counter>
                        ⌨ Keystrokes: {keystrokes} • 🖱 Mouse moves: {mouseMoves}
                    </Counter>

                    <Button
                        onClick={handleSaveSample}
                        disabled={!trackingActive || samples >= 10}
                    >
                        {samples < 10
                            ? `Save Sample (${samples}/10)`
                            : "Samples Complete ✅"}
                    </Button>

                    <Button
                        onClick={handleTraining}
                        disabled={samples < 10 || trainLoading}
                    >
                        {trainLoading ? "Training..." : "🚀 Train My Behavioral Model"}
                    </Button>

                    {trainMsg && (
                        <Message $success={trainMsg.startsWith("✅")}>{trainMsg}</Message>
                    )}
                </Card>
            )}

            {phase === "done" && (
                <Card>
                    <Title>✅ Model Trained</Title>
                    <p style={{ color: "#cbd5e1" }}>
                        Your personalized model is now locked and ready.
                        You can now log in.
                    </p>
                </Card>
            )}
        </Container>
    );
}
