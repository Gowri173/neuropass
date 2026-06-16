// src/PuzzleAuth.jsx
import React, { useEffect, useRef, useState } from "react";
import styled from "styled-components";
import { useNavigate, useLocation } from "react-router-dom";

/**
 * PuzzleAuth.jsx
 * - fetches /api/auth/puzzle-challenge
 * - shows a small draggable piece puzzle
 * - posts verification to /api/auth/puzzle-verify
 * - on success writes sessionStorage key puzzle_verified_{from}
 * - navigates back to /?from={from} so AuthFlow restores fields and can auto-submit
 */

/* ---------- Styled (small modal + layout) ---------- */
const Overlay = styled.div`
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
`;
const Modal = styled.div`
  background: #0f172a;
  color: #e6edf3;
  width: 360px;
  border-radius: 10px;
  padding: 14px;
  box-shadow: 0 8px 30px rgba(0,0,0,0.6);
  border: 1px solid rgba(255,255,255,0.04);
`;
const Header = styled.div`
  display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;
`;
const Title = styled.div`font-weight:700; color:#00b7ff;`;
const CloseBtn = styled.button`
  background:transparent; border:none; color:#9fbfdc; cursor:pointer; font-size:16px;
`;
const Hint = styled.div`font-size:12px; color:#9fbfdc; margin-bottom:8px;`;
const CanvasWrap = styled.div`width:320px; height:160px; position:relative; margin:0 auto;`;
const Small = styled.div`font-size:12px; color:#9fbfdc; margin-top:8px; display:flex; justify-content:space-between; align-items:center;`;
const VerifyBtn = styled.button`
  background: linear-gradient(90deg,#007aff,#00d4ff);
  color:white; border:none; padding:6px 10px; border-radius:6px; cursor:pointer;
`;

/* ---------- Puzzle Canvas (same logic but resilient) ---------- */
function PuzzleCanvas({ imageSrc, sessionId, pieceSize = 50, width = 320, height = 160, tolerance = 8, onSuccess }) {
    const canvasRef = useRef(null);
    const pieceRef = useRef(null);
    const [img, setImg] = useState(null);
    const [targetX, setTargetX] = useState(null);
    const [pieceY, setPieceY] = useState(20);
    const [dragX, setDragX] = useState(10);
    const [isDragging, setIsDragging] = useState(false);
    const [startTime, setStartTime] = useState(null);
    const [message, setMessage] = useState("Drag the piece to fit");

    useEffect(() => {
        setStartTime(Date.now());
    }, []);

    useEffect(() => {
        if (!imageSrc) return;
        const im = new Image();
        im.crossOrigin = "anonymous";
        im.onload = () => setImg(im);
        im.onerror = () => {
            // fallback to empty (will show blank)
            setImg(null);
        };
        im.src = imageSrc;
    }, [imageSrc]);

    useEffect(() => {
        // randomize target if not supplied
        const tx = Math.floor(Math.random() * (Math.floor(width * 0.7) - Math.floor(width * 0.25))) + Math.floor(width * 0.25);
        setTargetX(tx);
        setPieceY(Math.floor(Math.random() * (height - pieceSize - 10)) + 6);
        setDragX(10);
        setStartTime(Date.now());
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [img]);

    function createJigsawPath(ctx, x, y, size) {
        const s = size; const r = Math.max(6, Math.floor(s * 0.12));
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.lineTo(x + s - r, y);
        ctx.quadraticCurveTo(x + s, y, x + s, y + r);
        ctx.arc(x + s, y + s / 2, s / 8, -Math.PI / 2, Math.PI / 2, false);
        ctx.lineTo(x + s, y + s - r);
        ctx.quadraticCurveTo(x + s, y + s, x + s - r, y + s);
        ctx.lineTo(x + r, y + s);
        ctx.quadraticCurveTo(x, y + s, x, y + s - r);
        ctx.arc(x, y + s / 2, s / 8, Math.PI / 2, -Math.PI / 2, false);
        ctx.lineTo(x, y + r);
        ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.closePath();
    }

    function draw() {
        const canvas = canvasRef.current; if (!canvas) return;
        const ctx = canvas.getContext("2d");
        ctx.clearRect(0, 0, width, height);
        if (img) ctx.drawImage(img, 0, 0, width, height);
        // cutout
        if (targetX != null) {
            ctx.save();
            createJigsawPath(ctx, targetX, pieceY, pieceSize);
            ctx.globalCompositeOperation = "destination-out";
            ctx.fill();
            ctx.restore();

            ctx.save();
            createJigsawPath(ctx, targetX, pieceY, pieceSize);
            ctx.lineWidth = 2;
            ctx.strokeStyle = "rgba(0,0,0,0.25)";
            ctx.stroke();
            ctx.restore();
        }

        // piece canvas draw
        const pcanvas = pieceRef.current;
        if (!pcanvas) return;
        const pctx = pcanvas.getContext("2d");
        pcanvas.width = pieceSize;
        pcanvas.height = pieceSize;
        pctx.clearRect(0, 0, pieceSize, pieceSize);
        pctx.save();
        createJigsawPath(pctx, 0, 0, pieceSize);
        pctx.clip();
        if (img && targetX != null) {
            pctx.drawImage(img, targetX, pieceY, pieceSize, pieceSize, 0, 0, pieceSize, pieceSize);
        } else {
            // draw placeholder
            pctx.fillStyle = "#111827";
            pctx.fillRect(0, 0, pieceSize, pieceSize);
        }
        pctx.restore();
        pctx.save();
        pctx.lineWidth = 2;
        pctx.strokeStyle = "rgba(0,0,0,0.2)";
        createJigsawPath(pctx, 0, 0, pieceSize);
        pctx.stroke();
        pctx.restore();
    }

    useEffect(() => { draw(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [img, dragX, targetX]);

    function onPointerDown(e) { setIsDragging(true); e.currentTarget.setPointerCapture?.(e.pointerId); }
    function onPointerUp(e) { if (!isDragging) return; setIsDragging(false); e.currentTarget.releasePointerCapture?.(e.pointerId); attemptVerify(); }
    function onPointerMove(e) {
        if (!isDragging) return;
        const container = e.currentTarget.parentElement?.getBoundingClientRect();
        if (!container) return;
        let x = e.clientX - container.left - pieceSize / 2;
        x = Math.max(0, Math.min(width - pieceSize, x));
        setDragX(x);
    }

    async function attemptVerify() {
        const timeTaken = Date.now() - (startTime || Date.now());
        const delta = Math.abs(dragX - (targetX || 0));
        const frontendPass = delta <= tolerance;
        setMessage("Checking...");

        // try backend verify, fallback to frontend judgement
        try {
            const resp = await fetch("/api/auth/puzzle-verify", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ sessionId, offset: dragX, timeTaken }),
            });

            // handle HTML responses gracefully
            const ct = resp.headers.get("content-type") || "";
            if (ct.includes("application/json")) {
                const data = await resp.json();
                if (resp.ok && data.success) {
                    setMessage("Verified");
                    onSuccess({ verified: true, session: { sessionId, imageUrl: imageSrc } });
                } else {
                    setMessage(data?.message || "Incorrect — try again");
                    setTimeout(() => { setDragX(10); setStartTime(Date.now()); setMessage("Drag the piece to fit"); }, 700);
                }
            } else {
                // unexpected HTML response — fallback to frontendPass
                if (frontendPass) {
                    setMessage("Verified (offline fallback)");
                    onSuccess({ verified: true, session: { sessionId, imageUrl: imageSrc } });
                } else {
                    setMessage("Verification failed (server returned non-JSON)");
                    setTimeout(() => { setDragX(10); setStartTime(Date.now()); setMessage("Drag the piece to fit"); }, 700);
                }
            }
        } catch (err) {
            // network/abort -> fallback to frontend judgement
            if (err.name === "AbortError") {
                // ignore aborts (component unmounted)
                setMessage("Cancelled");
                return;
            }
            if (frontendPass) {
                setMessage("Verified (offline)");
                onSuccess({ verified: true, session: { sessionId, imageUrl: imageSrc } });
            } else {
                setMessage("Network error or incorrect");
                setTimeout(() => { setDragX(10); setStartTime(Date.now()); setMessage("Drag the piece to fit"); }, 700);
            }
        }
    }

    return (
        <div>
            <CanvasWrap>
                <canvas ref={canvasRef} width={width} height={height} className="rounded-md" aria-hidden />
                <canvas
                    ref={pieceRef}
                    width={pieceSize}
                    height={pieceSize}
                    onPointerDown={onPointerDown}
                    onPointerUp={onPointerUp}
                    onPointerMove={onPointerMove}
                    style={{
                        position: "absolute",
                        top: 0,
                        left: 0,
                        transform: `translate(${dragX}px, ${pieceY}px)`,
                        transition: isDragging ? "none" : "transform 0.16s ease",
                        touchAction: "none",
                        cursor: "grab",
                    }}
                    role="slider"
                    aria-valuemin={0}
                    aria-valuemax={width - pieceSize}
                    aria-valuenow={dragX}
                    aria-label="Puzzle piece"
                />
            </CanvasWrap>

            <Small>
                <div style={{ fontSize: 12 }}>{message}</div>
                <div>
                    <VerifyBtn onClick={() => { setDragX(targetX || 0); attemptVerify(); }}>Verify</VerifyBtn>
                </div>
            </Small>
        </div>
    );
}

/* ---------- Default challenge fetcher (robust) ---------- */
async function defaultFetchChallenge(signal) {
    // attempt server challenge
    const resp = await fetch("/api/auth/puzzle-challenge", { signal, credentials: "same-origin" });
    const ct = resp.headers.get("content-type") || "";
    if (!resp.ok) {
        throw new Error(`Challenge fetch failed: ${resp.status}`);
    }
    if (ct.includes("application/json")) {
        return resp.json(); // expected { sessionId, imageUrl }
    }

    // server responded with HTML (likely index.html) — fallback to a client-side challenge
    // create a simple data URL image (solid color gradient) so puzzle still displays
    const placeholder = createPlaceholderDataUrl();
    return { sessionId: null, imageUrl: placeholder };
}

function createPlaceholderDataUrl() {
    const w = 640, h = 320;
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    const ctx = c.getContext("2d");
    // gradient background
    const g = ctx.createLinearGradient(0, 0, w, h);
    g.addColorStop(0, "#0b1220");
    g.addColorStop(1, "#031628");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);
    // subtle pattern
    ctx.fillStyle = "rgba(255,255,255,0.02)";
    for (let i = 0; i < 80; i++) {
        ctx.fillRect(Math.random() * w, Math.random() * h, 2, 2);
    }
    return c.toDataURL("image/png");
}

/* ---------- Page component ---------- */
export default function PuzzleAuthPage({ fetchChallenge = defaultFetchChallenge }) {
    const navigate = useNavigate();
    const { search } = useLocation();
    const qs = new URLSearchParams(search || "");
    const from = qs.get("from") || qs.get("flow") || "login"; // fallback to login
    const mounted = useRef(true);

    const [loading, setLoading] = useState(true);
    const [challenge, setChallenge] = useState(null);
    const abortRef = useRef(null);

    useEffect(() => {
        mounted.current = true;
        const ac = new AbortController();
        abortRef.current = ac;

        (async () => {
            try {
                const chal = await fetchChallenge(ac.signal);
                if (!mounted.current) return;
                setChallenge(chal);
            } catch (err) {
                // ignore aborts during unmount; show fallback placeholder
                if (err.name === "AbortError") {
                    console.debug("[PuzzleAuthPage] challenge fetch aborted");
                    return;
                }
                console.warn("[PuzzleAuthPage] challenge fetch failed", err);
                // fallback to placeholder
                setChallenge({ sessionId: null, imageUrl: createPlaceholderDataUrl() });
            } finally {
                if (mounted.current) setLoading(false);
            }
        })();

        return () => {
            mounted.current = false;
            try { ac.abort(); } catch { }
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    function onSolved(result) {
        // result: { verified: true, session: { ... } }
        const meta = (result && result.session) ? result.session : { sessionId: challenge?.sessionId || null, imageUrl: challenge?.imageUrl || null };
        // persist verification token; AuthFlow will read this and auto-submit
        try {
            sessionStorage.setItem(`puzzle_verified_${from}`, JSON.stringify({ verified: true, session: meta }));
            console.debug(`[PuzzleAuthPage] stored verification puzzle_verified_${from}`);
        } catch (e) {
            console.warn("failed to store puzzle verification", e);
        }

        // navigate back to auth page so it can restore fields and auto-submit
        // Use query param ?from=login or ?from=register so AuthFlow knows what to restore
        // keep navigation same-origin to avoid losing sessionStorage
        navigate(`/?from=${from}`, { replace: true });
    }

    function handleClose() {
        // closing means user canceled — do not clear saved fields (AuthFlow will still restore them)
        try { sessionStorage.removeItem(`puzzle_verified_${from}`); } catch { }
        navigate("/", { replace: true });
    }

    return (
        <Overlay>
            <Modal role="dialog" aria-modal="true">
                <Header>
                    <Title>Complete puzzle</Title>
                    <CloseBtn onClick={handleClose} aria-label="Close">✕</CloseBtn>
                </Header>

                <Hint>Move the puzzle piece into place. This verifies you are not a bot.</Hint>

                {loading ? (
                    <div style={{ height: 160, display: "flex", alignItems: "center", justifyContent: "center" }}>Loading...</div>
                ) : (
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                        <PuzzleCanvas
                            imageSrc={challenge?.imageUrl}
                            sessionId={challenge?.sessionId}
                            onSuccess={(res) => {
                                // call backend verify if sessionId present, otherwise fallback
                                onSolved(res);
                            }}
                        />
                    </div>
                )}

                <Small>
                    <div style={{ color: "#9fbfdc" }}>You will be returned to the form after solving.</div>
                    <div />
                </Small>
            </Modal>
        </Overlay>
    );
}
