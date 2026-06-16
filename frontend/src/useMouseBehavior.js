// src/useMouseBehavior.js
import { useEffect, useRef, useState, useCallback } from "react";

/**
 * Mouse behavior capture — fixed to send user_id, session_id
 */
export default function useMouseBehavior(userId, opts = {}) {
    const API_BASE = opts.apiBase || process.env.REACT_APP_API_BASE || "http://localhost:8000";
    const ENDPOINT = `${API_BASE.replace(/\/+$/, "")}/api/mouse_events`;

    const buffer = useRef([]);
    const [sessionId, setSessionId] = useState(
        () => `${Date.now()}_${Math.random().toString(36).slice(2)}`
    );
    const [tracking, setTracking] = useState(true);

    /** ---------------- RECORD EVENT ---------------- */
    const recordEvent = useCallback(
        (e) => {
            if (!userId || !tracking) return;

            buffer.current.push({
                user_id: userId,
                session_id: sessionId,
                type: e.type,
                x: e.clientX ?? null,
                y: e.clientY ?? null,
                ts: Date.now(),
            });
        },
        [userId, sessionId, tracking]
    );

    /** ---------------- SEND PAYLOAD ---------------- */
    const sendPayload = useCallback(
        async (payload) => {
            try {
                if (navigator.sendBeacon) {
                    const blob = new Blob([JSON.stringify(payload)], { type: "application/json" });
                    if (navigator.sendBeacon(ENDPOINT, blob)) return { ok: true };
                }
            } catch { }

            try {
                await fetch(ENDPOINT, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                    keepalive: true,
                });
                return { ok: true };
            } catch (err) {
                return { ok: false, error: err };
            }
        },
        [ENDPOINT]
    );

    /** ---------------- FLUSH ---------------- */
    const flushMouseData = useCallback(async () => {
        if (!buffer.current.length) return { ok: true, sent: 0 };

        const eventsCopy = buffer.current.slice();
        buffer.current = [];

        const payload = {
            client_wall_ts: Date.now(),
            session_id: sessionId,
            events: eventsCopy,
        };

        const res = await sendPayload(payload);
        if (!res.ok) {
            buffer.current = eventsCopy.concat(buffer.current);
            return { ok: false, sent: 0 };
        }

        return { ok: true, sent: eventsCopy.length };
    }, [sessionId, sendPayload]);

    /** ---------------- NEW SESSION ---------------- */
    const newSession = useCallback((externalId = null) => {
        const newId = externalId || `${Date.now()}_${Math.random().toString(36).slice(2)}`;
        setSessionId(newId);
        buffer.current = [];
        return newId;
    }, []);

    /** ---------------- START/STOP TRACKING ---------------- */
    const stopTracking = useCallback(() => setTracking(false), []);
    const startTracking = useCallback(() => setTracking(true), []);

    /** ---------------- LIFECYCLE ---------------- */
    useEffect(() => {
        if (!userId || !tracking) return () => { };

        window.addEventListener("mousemove", recordEvent, { passive: true });
        window.addEventListener("mousedown", recordEvent, { passive: true });
        window.addEventListener("mouseup", recordEvent, { passive: true });

        return () => {
            window.removeEventListener("mousemove", recordEvent);
            window.removeEventListener("mousedown", recordEvent);
            window.removeEventListener("mouseup", recordEvent);
        };
    }, [userId, tracking, recordEvent]);

    return {
        sessionId,
        flushMouseData,
        newSession,
        stopTracking,
        startTracking,
    };
}
