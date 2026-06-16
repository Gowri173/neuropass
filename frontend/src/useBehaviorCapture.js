// src/useBehaviorCapture.js
import { useEffect, useRef, useCallback } from "react";

// FINAL VERSION — no auto-flush, login gets FULL keystroke sequence
export default function useBehaviorCapture(userId, opts = {}) {
    const generateUUID = () =>
        window.crypto?.randomUUID?.() ||
        "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
            const r = (Math.random() * 16) | 0;
            const v = c === "x" ? r : (r & 0x3) | 0x8;
            return v.toString(16);
        });

    const API_BASE = opts.apiBase || process.env.REACT_APP_API_BASE || "http://localhost:8000";
    const ENDPOINT = `${API_BASE.replace(/\/+$/, "")}/api/events`;

    const sessionId = useRef(generateUUID());
    const buffer = useRef([]);

    const nowPerf = () => performance.timeOrigin + performance.now();

    /** SEND PAYLOAD **/
    const sendPayload = useCallback(async (payload) => {
        try {
            await fetch(ENDPOINT, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
                keepalive: true
            });
            return true;
        } catch (err) {
            console.warn("sendPayload failed:", err);
            return false;
        }
    }, [ENDPOINT]);

    /** FLUSH MANUALLY ONLY **/
    const flush = useCallback(async () => {
        if (!buffer.current.length) return { ok: true, sent: 0 };

        const eventsCopy = buffer.current.slice();
        buffer.current = [];

        const payload = {
            user_id: userId || null,
            session_id: sessionId.current,
            client_wall_ts: Date.now(),
            client_perf_timeOrigin: performance.timeOrigin,
            events: eventsCopy
        };

        const ok = await sendPayload(payload);
        if (!ok) {
            buffer.current = eventsCopy.concat(buffer.current);
            return { ok: false, sent: 0 };
        }
        return { ok: true, sent: eventsCopy.length };
    }, [sendPayload, userId]);

    /** ADD KEY EVENT TO BUFFER **/
    const handleKeyEvent = useCallback((e) => {
        if (!userId) return;

        buffer.current.push({
            type: e.type,
            key: e.key,
            code: e.code,
            repeat: !!e.repeat,
            perf_ts: nowPerf(),
            wall_ts: Date.now(),
            user_id: userId,
            session_id: sessionId.current
        });
    }, [userId]);

    /** LISTENERS **/
    useEffect(() => {
        if (!userId) return () => { };

        window.addEventListener("keydown", handleKeyEvent, { passive: true });
        window.addEventListener("keyup", handleKeyEvent, { passive: true });

        return () => {
            window.removeEventListener("keydown", handleKeyEvent);
            window.removeEventListener("keyup", handleKeyEvent);

            // DO NOT FLUSH HERE during login!
        };
    }, [userId, handleKeyEvent]);

    return {
        getSessionId: () => sessionId.current,
        sessionId: sessionId.current,
        flush,
        newSession: () => {
            const id = generateUUID();
            sessionId.current = id;
            buffer.current = [];
            return id;
        }
    };
}
