# main.py
# ======================================================
# NeuroPass Backend — main.py (Siamese-TCN primary)
# Revised: robust timestamp handling, stable sigma/threshold (MAD), richer debug,
# hybrid decision rule, safer sequence standardization.
# ======================================================

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
import numpy as np
import os
import bcrypt
from datetime import datetime
from extract_features import extract_features, extract_sequence_features
from extract_mouse_features import extract_mouse_features
import traceback
import joblib
import math
import time

# ---------------- PyTorch (Siamese TCN) ----------------
PT_AVAILABLE = True
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torch.utils.data import Dataset, DataLoader
except Exception as e:
    PT_AVAILABLE = False
    print("⚠️ PyTorch not available:", e)

# ---------------- App & CORS ----------------
app = FastAPI(title="NeuroPass API (Siamese-TCN primary)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- MongoDB ----------------
client = MongoClient("mongodb://localhost:27017")
db = client["neuropass"]
users_col = db["users"]
keystroke_col = db["events"]
mouse_col = db["mouse_events"]
transactions_col = db["transactions"]
debug_login_col = db["debug_login"]

# ---------------- Models directory ----------------
BASE_DIR = os.path.dirname(__file__)
MODEL_DIR = os.path.abspath(os.path.join(BASE_DIR, "../models"))
os.makedirs(MODEL_DIR, exist_ok=True)

SIAMESE_PATH = os.path.join(MODEL_DIR, "siamese_tcn.pt")
# IMPORTANT: extract_sequence_features returns 5 features per timestep by default
SIAMESE_INPUT_DIM = 5
SIAMESE_CHANNELS = [32, 64, 128]
SIAMESE_EMB_DIM = 128
SIAMESE_KERNEL = 3
SIAMESE_DROPOUT = 0.1
TRIPLET_MARGIN = 0.2

DEVICE = None
if PT_AVAILABLE:
    DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# ---------------- Utilities ----------------


def sanitize_array(arr):
    a = np.array(arr, dtype=float)
    a = np.nan_to_num(a, nan=0.0, posinf=1e6, neginf=-1e6)
    a = np.clip(a, -1e6, 1e6)
    return a


def seconds_to_milliseconds_if_needed(ts):
    """
    If ts looks like seconds (e.g., ~1e9), convert to ms. If already ms (~1e12), leave.
    """
    try:
        t = float(ts)
        if t <= 0:
            return int(datetime.utcnow().timestamp() * 1000)
        # heuristic: timestamps < 1e11 are likely seconds (or small ms); convert to ms
        if t < 1e11:
            # If it's clearly in seconds (<1e11), multiply by 1000
            return int(round(t * 1000))
        return int(round(t))
    except Exception:
        return int(datetime.utcnow().timestamp() * 1000)


def compute_threshold_from_scores(scores):
    """Legacy helper retained but not primary; keep safe fallback behavior."""
    try:
        s = np.array(scores, dtype=float)
        s = s[np.isfinite(s)]
        if s.size == 0:
            return 0.6
        s = np.clip(s, 0.0, 1.0)
        p10 = np.percentile(s, 10)
        mean = s.mean()
        std = s.std()
        candidate = min(mean - 0.3 * std, p10 + 0.02)
        thr = float(np.clip(candidate, 0.2, 0.95))
        if not np.isfinite(thr):
            return 0.6
        return round(thr, 3)
    except Exception:
        return 0.6


# ---------------- Sequence standardization helper ----------------
def standardize_seq(X, feat_dim: int):
    """
    Ensure X has shape (n, feat_dim). If columns differ, pad/truncate columns to feat_dim.
    Handles 1D or flattened inputs safely.
    """
    if X is None:
        return None
    X = np.array(X, dtype=float)
    # If flattened 1D (total_len), attempt to infer rows
    if X.ndim == 1:
        if X.size == 0:
            return np.zeros((1, feat_dim), dtype=float)
        # if length divisible by feat_dim, reshape; else make single row and pad/truncate
        if X.size % feat_dim == 0:
            X = X.reshape((-1, feat_dim))
        else:
            # treat as single row of features
            row = np.zeros((1, feat_dim), dtype=float)
            copy_n = min(feat_dim, X.size)
            row[0, :copy_n] = X[:copy_n]
            return row
    if X.ndim == 2:
        n_cols = X.shape[1]
        if n_cols == feat_dim:
            return X
        if n_cols < feat_dim:
            pad_cols = np.zeros((X.shape[0], feat_dim - n_cols), dtype=float)
            Xp = np.hstack([X, pad_cols])
            return Xp
        # n_cols > feat_dim -> truncate columns on the right
        return X[:, :feat_dim]
    # any other shape: flatten then attempt to shape as above
    flat = X.flatten()
    if flat.size % feat_dim == 0:
        return flat.reshape((-1, feat_dim))
    # fallback: single row padded/truncated
    row = np.zeros((1, feat_dim), dtype=float)
    copy_n = min(feat_dim, flat.size)
    row[0, :copy_n] = flat[:copy_n]
    return row


# ---------------- PyTorch Siamese model ----------------
if PT_AVAILABLE:
    class Chomp1d(nn.Module):
        def __init__(self, chomp_size):
            super().__init__()
            self.chomp_size = chomp_size

        def forward(self, x):
            return x[:, :, :-self.chomp_size].contiguous()

    class TemporalBlock(nn.Module):
        def __init__(self, in_ch, out_ch, kernel_size, dilation, padding, dropout=0.1):
            super().__init__()
            self.conv1 = nn.Conv1d(
                in_ch, out_ch, kernel_size, padding=padding, dilation=dilation)
            self.chomp1 = Chomp1d(padding)
            self.bn1 = nn.BatchNorm1d(out_ch)
            self.relu1 = nn.ReLU()
            self.dropout1 = nn.Dropout(dropout)

            self.conv2 = nn.Conv1d(
                out_ch, out_ch, kernel_size, padding=padding, dilation=dilation)
            self.chomp2 = Chomp1d(padding)
            self.bn2 = nn.BatchNorm1d(out_ch)
            self.relu2 = nn.ReLU()
            self.dropout2 = nn.Dropout(dropout)

            self.net = nn.Sequential(self.conv1, self.chomp1, self.bn1, self.relu1, self.dropout1,
                                     self.conv2, self.chomp2, self.bn2, self.relu2, self.dropout2)
            self.downsample = nn.Conv1d(
                in_ch, out_ch, 1) if in_ch != out_ch else None
            self.relu = nn.ReLU()

        def forward(self, x):
            out = self.net(x)
            res = x if self.downsample is None else self.downsample(x)
            return self.relu(out + res)

    class TCNBranch(nn.Module):
        def __init__(self, input_dim, channels=[32, 64, 128], kernel_size=3, dropout=0.1):
            super().__init__()
            layers = []
            prev = input_dim
            for i, ch in enumerate(channels):
                dilation = 2 ** i
                padding = (kernel_size - 1) * dilation
                layers.append(TemporalBlock(
                    prev, ch, kernel_size, dilation, padding, dropout))
                prev = ch
            self.tcn = nn.Sequential(*layers)
            self.global_pool = nn.AdaptiveAvgPool1d(1)

        def forward(self, x):
            # x (B, seq_len, feat) -> (B, feat, seq)
            x = x.transpose(1, 2)
            y = self.tcn(x)
            pooled = self.global_pool(y).squeeze(-1)
            return pooled

    class SiameseTCN(nn.Module):
        def __init__(self, input_dim, channels=[32, 64, 128], emb_dim=128, kernel_size=3, dropout=0.1):
            super().__init__()
            self.branch = TCNBranch(input_dim, channels, kernel_size, dropout)
            last_ch = channels[-1]
            self.project = nn.Sequential(
                nn.Linear(last_ch, 256),
                nn.ReLU(),
                nn.Dropout(dropout),
                nn.Linear(256, emb_dim)
            )

        def forward(self, x):
            z = self.branch(x)
            v = self.project(z)
            v = F.normalize(v, p=2, dim=1)
            return v

    def batch_all_triplet_mining(embeddings, labels, margin=TRIPLET_MARGIN):
        with torch.no_grad():
            N = embeddings.size(0)
            dist = torch.cdist(embeddings, embeddings, p=2)
            triplets = []
            for i in range(N):
                anchor_label = labels[i].item()
                pos_idx = torch.where(labels == anchor_label)[0]
                neg_idx = torch.where(labels != anchor_label)[0]
                pos_idx = pos_idx[pos_idx != i]
                if len(pos_idx) == 0 or len(neg_idx) == 0:
                    continue
                pos_dists = dist[i][pos_idx]
                pos = pos_idx[torch.argmax(pos_dists)].item()
                neg_dists = dist[i][neg_idx]
                semi_mask = (neg_dists > dist[i][pos]) & (
                    neg_dists < dist[i][pos] + margin)
                if semi_mask.any():
                    neg = neg_idx[torch.where(semi_mask)[0][0]].item()
                else:
                    neg = neg_idx[torch.argmin(neg_dists)].item()
                triplets.append((i, pos, neg))
        return triplets

    def triplet_loss_from_indices(embeddings, triplets, margin=TRIPLET_MARGIN):
        if len(triplets) == 0:
            return embeddings.sum()*0.0
        a = torch.stack([embeddings[i] for i, _, _ in triplets])
        p = torch.stack([embeddings[j] for _, j, _ in triplets])
        n = torch.stack([embeddings[k] for _, _, k in triplets])
        pos = F.pairwise_distance(a, p)
        neg = F.pairwise_distance(a, n)
        loss = F.relu(pos - neg + margin).mean()
        return loss

    class KeystrokeDataset(torch.utils.data.Dataset):
        def __init__(self, rows, labels, seq_len=None, feat_dim=SIAMESE_INPUT_DIM):
            self.rows = [np.array(r, dtype=float) for r in rows]
            self.labels = np.array(labels, dtype=int)
            self.feat_dim = feat_dim
            self.seq_len = seq_len
            if self.seq_len is None:
                lens = [r.size // feat_dim for r in self.rows]
                self.seq_len = max(1, max(lens))

        def __len__(self):
            return len(self.rows)

        def __getitem__(self, idx):
            r = self.rows[idx]
            target = self.seq_len * self.feat_dim
            if r.size < target:
                padded = np.zeros((target,), dtype=float)
                padded[:r.size] = r
                r = padded
            elif r.size > target:
                r = r[:target]
            seq = r.reshape((self.seq_len, self.feat_dim))
            return torch.tensor(seq, dtype=torch.float32), int(self.labels[idx])

    def load_siamese_model():
        model = SiameseTCN(SIAMESE_INPUT_DIM, SIAMESE_CHANNELS,
                           SIAMESE_EMB_DIM, SIAMESE_KERNEL, SIAMESE_DROPOUT)
        if os.path.exists(SIAMESE_PATH):
            try:
                model.load_state_dict(torch.load(
                    SIAMESE_PATH, map_location=DEVICE))
                print("✅ Loaded siamese model:", SIAMESE_PATH)
            except Exception as e:
                print("⚠ Failed loading siamese model:", e)
        if DEVICE is not None:
            model.to(DEVICE)
        model.eval()
        return model

    def compute_embedding_from_events(evs, model=None, max_seq_len=None):
        """
        Build sequence features using extract_sequence_features and run through siamese model.
        Returns embedding list (floats).
        """
        # Quick sanity: ensure we have events and convert DB objects to plain dicts
        if not evs or len(evs) == 0:
            raise ValueError("No events to compute embedding")

        # Extract sequence features (extract_sequence_features should return (X, mask))
        X, _mask = extract_sequence_features(evs)
        if X is None or (isinstance(X, np.ndarray) and X.size == 0):
            raise ValueError("No sequence features extracted")

        Xs = standardize_seq(X, SIAMESE_INPUT_DIM)
        if Xs is None or Xs.size == 0:
            raise ValueError("Standardized sequence empty")

        seq_len = Xs.shape[0]
        if max_seq_len is None:
            target_seq = max(1, seq_len)
        else:
            target_seq = max(1, int(max_seq_len))

        if seq_len < target_seq:
            pad_n = target_seq - seq_len
            pad = np.zeros((pad_n, SIAMESE_INPUT_DIM), dtype=float)
            Xp = np.vstack([Xs, pad])
        else:
            Xp = Xs[:target_seq, :]

        seq = Xp.reshape(
            (1, Xp.shape[0], SIAMESE_INPUT_DIM)).astype(np.float32)
        x = torch.tensor(seq, dtype=torch.float32)
        if DEVICE is not None:
            x = x.to(DEVICE)
        if model is None:
            model = load_siamese_model()
        with torch.no_grad():
            emb = model(x).cpu().numpy().squeeze()
        # ensure numerical stability and normalization
        emb = np.nan_to_num(emb, nan=0.0, posinf=1e6, neginf=-1e6)
        norm = np.linalg.norm(emb)
        if norm == 0 or not np.isfinite(norm):
            # avoid zero-vector; small random perturbation to prevent exact zeros
            emb = emb + np.random.normal(scale=1e-6, size=emb.shape)
            norm = np.linalg.norm(emb)
        emb = emb / (norm + 1e-12)
        return emb.tolist()

    # ---------------- Helper: robust statistics ----------------
    def mad(arr):
        a = np.array(arr, dtype=float)
        med = np.median(a)
        return np.median(np.abs(a - med))

    # ---------------- Robust per-user threshold function (REPLACEMENT) ----------------
    def compute_and_store_siamese_threshold(user_id, gallery, model=None, max_impostors=500, impostor_per_user=2, percentile_floor=5):
        """
        Robust per-user threshold computation.

        Steps:
        - compute centroid and genuine distances for this user's gallery
        - estimate sigma via MAD (robust), fallback to std, and enforce a gentle per-user minimum
        - compute genuine scores: score = exp(-dist / sigma)
        - build an impostor pool by sampling up to `impostor_per_user` embeddings from many other users' galleries
        - compute impostor scores vs this user's gallery (all pairwise)
        - choose threshold t in [0,1] minimizing |FAR - FRR| (EER-like). Tie-breaker: prefer lower FAR.
        - if impostor pool is empty, choose threshold = max(percentile(genuine_scores, percentile_floor) - small_delta, 0.05)
        - store threshold and metadata in users_col
        """
        try:
            if not gallery or len(gallery) == 0:
                return None, 0, [], None

            G = np.array(gallery, dtype=float)  # (G, D)
            centroid = np.mean(G, axis=0)
            genuine_dists = np.linalg.norm(
                G - centroid[None, :], axis=1)  # shape (G,)

            # robust sigma via MAD -> approx std
            def _mad(a):
                a = np.array(a, dtype=float)
                med = np.median(a)
                return np.median(np.abs(a - med))

            mad_val = _mad(genuine_dists)
            sigma_est = float(mad_val * 1.4826)  # approximate std
            if sigma_est <= 1e-9:
                sigma_est = float(np.std(genuine_dists))
            # gentle per-user minimum sigma: relative to mean distance (avoid absolute global floor)
            mean_d = float(np.mean(genuine_dists)
                           ) if genuine_dists.size > 0 else 0.0
            # 25% of mean-dist, but at least 0.005
            min_sigma = max(0.005, max(1e-3, mean_d * 0.25))
            sigma = float(max(sigma_est, min_sigma))

            # compute genuine scores (higher = more similar)
            genuine_scores = np.array(
                [float(np.exp(- (d / (sigma + 1e-12)))) for d in genuine_dists], dtype=float)

            # Build impostor pool: sample up to max_impostors embeddings from other users
            impostor_embs = []
            # iterate users, sample up to impostor_per_user embeddings from each
            for other in users_col.find({"userId": {"$ne": user_id}}, {"siamese_gallery": 1}).batch_size(100):
                other_gallery = other.get("siamese_gallery") or []
                if not other_gallery:
                    continue
                # sample up to impostor_per_user from this user's gallery
                sample = other_gallery[:impostor_per_user]
                for emb in sample:
                    impostor_embs.append(np.array(emb, dtype=float))
                if len(impostor_embs) >= max_impostors:
                    break

            impostor_scores = np.array([])
            if len(impostor_embs) > 0:
                impostor_embs = np.vstack(impostor_embs)  # (I, D)
                # compute pairwise distances: each gallery emb vs impostors -> scores
                all_imp_scores = []
                for emb in G:
                    ds = np.linalg.norm(emb - impostor_embs, axis=1)
                    sc = np.exp(- (ds / (sigma + 1e-12)))
                    all_imp_scores.extend(sc.tolist())
                impostor_scores = np.array(all_imp_scores, dtype=float)

            # threshold selection
            new_thr = None
            if impostor_scores.size > 0 and genuine_scores.size > 0:
                # search candidates with reasonable resolution
                candidates = np.linspace(0.0, 1.0, 1001)
                best_t = None
                best_diff = 1.0 + 1e-9
                best_far = None
                for t in candidates:
                    FAR = float(np.mean(impostor_scores >= t))
                    FRR = float(np.mean(genuine_scores < t))
                    diff = abs(FAR - FRR)
                    if (diff < best_diff - 1e-12) or (abs(diff - best_diff) < 1e-12 and (best_far is None or FAR < best_far)):
                        best_diff = diff
                        best_t = float(t)
                        best_far = FAR
                # avoid tiny thresholds caused by edge cases by clamping to a per-user lower bound:
                # lower_bound = max( percentile(impostor_scores, 99) + small_margin, percentile(genuine_scores, 5) - small_margin )
                imp99 = float(np.percentile(impostor_scores, 99)
                              ) if impostor_scores.size > 0 else 0.0
                gen05 = float(np.percentile(genuine_scores, 5)
                              ) if genuine_scores.size > 0 else 0.0
                lower_bound = max(imp99 + 0.01, gen05 - 0.01, 0.02)
                new_thr = float(np.clip(best_t, lower_bound, 0.99))
            else:
                # fallback: no impostors or no genuine scores (shouldn't happen)
                if genuine_scores.size > 0:
                    # pick lower percentile of genuine scores as baseline (conservative)
                    p = float(np.percentile(genuine_scores, percentile_floor))
                    # push it down slightly to account for variation
                    new_thr = float(np.clip(p - 0.02, 0.02, 0.95))
                else:
                    new_thr = 0.6

            if not np.isfinite(new_thr):
                new_thr = 0.6

            # store metadata to user doc for auditing
            users_col.update_one({"userId": user_id}, {
                "$set": {
                    "behavior_threshold": float(new_thr),
                    "siamese_sigma": float(sigma),
                    "siamese_centroid": list(centroid),
                    "genuine_scores": genuine_scores.tolist(),
                    "impostor_stats": {
                        "count": int(impostor_scores.size),
                        "mean": float(np.mean(impostor_scores)) if impostor_scores.size > 0 else None,
                        "std": float(np.std(impostor_scores)) if impostor_scores.size > 0 else None,
                    },
                    "threshold_method": "per-user-mad-eer-sampling",
                    "threshold_created_at": datetime.utcnow()
                }
            })
            return float(new_thr), int(genuine_scores.size), genuine_scores.tolist(), float(sigma)

        except Exception as exc:
            print("⚠ compute_and_store_siamese_threshold (robust) error:",
                  exc, traceback.format_exc())
            return None, 0, [], None

# ---------------- Routes (endpoints kept) ----------------


@app.get("/")
def root():
    return {"message": "NeuroPass API (Siamese-TCN primary) running"}


@app.post("/api/events")
async def save_events(request: Request):
    data = await request.json()
    events = data.get("events", [])
    inserted = 0
    docs = []

    if not isinstance(events, list):
        return {"status": "error", "message": "events must be a list"}

    for e in events:
        user_id = e.get("user_id") or e.get("userId")
        session_id = e.get("session_id") or e.get("sessionId")
        perf_ts = e.get("perf_ts")
        wall_ts = e.get("wall_ts")
        legacy_ts = e.get("ts") or e.get("timestamp")
        ts_raw = perf_ts or wall_ts or legacy_ts
        ts = seconds_to_milliseconds_if_needed(ts_raw) if ts_raw is not None else int(
            datetime.utcnow().timestamp() * 1000)

        if not user_id or not session_id:
            print("⚠️ Dropped event (missing user_id/session_id):", e)
            continue

        docs.append({
            "user_id": user_id,
            "session_id": session_id,
            "type": e.get("type"),
            "key": e.get("key"),
            "code": e.get("code"),
            "repeat": e.get("repeat", False),
            "ts": int(ts),
            "perf_ts": perf_ts,
            "wall_ts": wall_ts,
        })

    if docs:
        keystroke_col.insert_many(docs)
        inserted = len(docs)

    print(f"📥 Saved {inserted} keystroke events")

    return {
        "status": "ok",
        "inserted": inserted,
        "message": f"Inserted {inserted} keystroke events"
    }


@app.post("/api/mouse_events")
async def save_mouse_events(request: Request):
    data = await request.json()
    events = data.get("events", [])
    if not events:
        return {"status": "error", "message": "No mouse events provided"}
    docs = []
    for e in events:
        user_id = e.get("userId") or e.get("user_id")
        session_id = e.get("sessionId") or e.get("session_id")
        ts_raw = e.get("ts")
        ts = seconds_to_milliseconds_if_needed(ts_raw) if ts_raw is not None else int(
            datetime.utcnow().timestamp() * 1000)
        if not user_id or not session_id:
            continue
        docs.append({
            "user_id": user_id,
            "session_id": session_id,
            "type": e.get("type"),
            "x": float(e.get("x") or 0),
            "y": float(e.get("y") or 0),
            "ts": int(ts)
        })
    if docs:
        mouse_col.insert_many(docs)
    print(f"📥 Saved {len(docs)} mouse events")
    return {"status": "ok", "message": f"Inserted {len(docs)} mouse events"}


@app.post("/api/register")
def register_user(payload: dict):
    user_id = payload.get("user_id")
    password = payload.get("password")
    if not user_id or not password:
        return {"status": "error", "message": "Missing user_id or password"}
    if users_col.find_one({"userId": user_id}):
        return {"status": "error", "message": "User already exists"}
    hashed_pw = bcrypt.hashpw(password.encode(
        "utf-8"), bcrypt.gensalt()).decode("utf-8")
    users_col.insert_one({
        "userId": user_id,
        "password_hash": hashed_pw,
        "balance": 1000.0,
        "created_at": datetime.utcnow(),
        "behavior_threshold": 0.6,
        "siamese_gallery": [],
        "siamese_centroid": None,
        "siamese_sigma": 1.0
    })
    print(f"🆕 Registered user {user_id} (threshold=0.6, balance=1000)")
    return {"status": "ok", "message": "User registered. Collect sessions for training."}


@app.post("/api/login")
async def login_user(payload: dict):
    user_id = payload.get("user_id")
    password = payload.get("password")
    session_id = payload.get("session_id")
    print(f"{user_id}      {session_id}       {password}")
    if not user_id or not password or not session_id:
        return {
            "decision": "deny",
            "score": 0.0,
            "reason": "Missing credentials or session_id"
        }

    user = users_col.find_one({"userId": user_id})
    if not user:
        return {"decision": "deny", "score": 0.0, "reason": "User not found"}

    if not bcrypt.checkpw(password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        return {"decision": "deny", "score": 0.0, "reason": "Behavior mismatch"}

    evs = list(keystroke_col.find({
        "session_id": session_id,
        "user_id": user_id
    }))

    if not evs:
        return {
            "decision": "deny",
            "score": 0.0,
            "reason": "No keystroke events for session"
        }

    if not PT_AVAILABLE:
        return {
            "decision": "deny",
            "score": 0.0,
            "reason": "Siamese model not available on server (PyTorch missing)"
        }

    try:
        model = load_siamese_model()
    except Exception as e:
        print("⚠ Could not load siamese model:", e)
        return {"decision": "deny", "score": 0.0, "reason": "Siamese model load failed"}

    try:
        emb = np.array(compute_embedding_from_events(
            evs, model=model), dtype=float)
    except Exception as e:
        print("⚠ Embedding failed:", e)
        return {"decision": "deny", "score": 0.0, "reason": "Embedding failed"}

    gallery = user.get("siamese_gallery", []) or []
    centroid = user.get("siamese_centroid", None)

    if centroid is not None:
        centroid_arr = np.array(centroid, dtype=float)
        dist = float(np.linalg.norm(emb - centroid_arr))
    elif gallery:
        dists = [float(np.linalg.norm(emb - np.array(g, dtype=float)))
                 for g in gallery]
        dist = float(min(dists))
    else:
        return {
            "decision": "deny",
            "score": 0.0,
            "reason": "User has no siamese gallery; enroll first"
        }

    sigma = float(user.get("siamese_sigma", 1.0))
    raw_score = float(np.exp(-dist / (sigma + 1e-9)))

    threshold = float(user.get("behavior_threshold", 0.6))
    adaptive_margin = max(0.02, 0.05 * threshold)
    proximity = abs(raw_score - threshold)

    # hybrid decision: score OR centroid-distance rule
    centroid_accept = True
    if user.get("genuine_scores_summary"):
        # compute centroid-based rule: mean genuine dist + 2*std
        gmean = user.get("genuine_scores_summary", {}).get("mean")
        # We stored genuine_scores_summary in score-space; recompute distances if centroid exists
    centroid_mean = None
    centroid_std = None
    if user.get("siamese_centroid") is not None and user.get("genuine_scores_summary") is not None:
        # Recompute distances of gallery to centroid if available (safer)
        gallery_local = user.get("siamese_gallery", []) or []
        if len(gallery_local) > 0:
            G = np.array(gallery_local, dtype=float)
            cent = np.array(user.get("siamese_centroid"), dtype=float)
            gdists = np.linalg.norm(G - cent[None, :], axis=1)
            centroid_mean = float(np.mean(gdists))
            centroid_std = float(np.std(gdists))
            if dist <= (centroid_mean + 2.0 * centroid_std + 1e-9):
                centroid_accept = True
    lower = max(0.0, threshold - 0.008)
    upper = min(1.0, threshold + 0.008)
    decision = "accept" if (((raw_score >= lower) and (
        raw_score <= upper)) or centroid_accept) else "deny"

    debug = {
        "distance": dist,
        "raw_score": raw_score,
        "threshold": threshold,
        "adaptive_margin": adaptive_margin,
        "proximity": round(float(proximity), 6),
        "sigma_used": sigma,
        "centroid_mean": centroid_mean,
        "centroid_std": centroid_std,
        "centroid_accept": centroid_accept,
        "gallery_size": len(gallery),
        "embedding_norm": float(np.linalg.norm(emb))
    }

    print(
        f"🔐 Login {user_id} session {session_id} → "
        f"raw {raw_score:.3f}, thr {threshold:.3f}, prox {proximity:.4f} => {decision}"
    )

    # Save debug doc for offline triage
    try:
        dbg = {
            "user_id": user_id,
            "session_id": session_id,
            "timestamp": datetime.utcnow(),
            "ev_count": len(evs),
            "distance": dist,
            "raw_score": raw_score,
            "threshold": threshold,
            "decision": decision,
            "debug": debug
        }
        debug_login_col.insert_one(dbg)
    except Exception as e:
        print("⚠ failed to save debug login doc:", e)

    return {
        "decision": decision,
        "score": round(raw_score, 3),
        "reason": "Behavior verified" if decision == "accept" else "Behavior mismatch",
        "debug": debug
    }


@app.post("/api/train_user")
def train_user(payload: dict):
    if not PT_AVAILABLE:
        return {"status": "error", "message": "PyTorch not available on server."}

    user_id = payload.get("user_id")
    if not user_id:
        return {"status": "error", "message": "user_id required"}

    min_sessions = int(payload.get("min_sessions", 5))
    epochs = int(payload.get("epochs", 8))
    batch_p = int(payload.get("batch_p", 8))
    batch_k = int(payload.get("batch_k", 8))
    lr = float(payload.get("lr", 1e-3))
    force = bool(payload.get("force", False))

    candidate_users = []
    for u in users_col.find():
        uid = u.get("userId")
        sess_count = len(keystroke_col.distinct(
            "session_id", {"user_id": uid}))
        if sess_count >= min_sessions:
            candidate_users.append(uid)

    seq_list = []
    labels = []
    label_map = {}
    next_label = 0

    for uid in candidate_users:
        sess_ids = keystroke_col.distinct("session_id", {"user_id": uid})
        sess_sel = sess_ids[-min_sessions:]
        for s in sess_sel:
            evs = list(keystroke_col.find({"session_id": s, "user_id": uid}))
            if not evs:
                continue
            try:
                X, _mask = extract_sequence_features(evs)
            except Exception:
                continue
            if X is None or X.size == 0:
                continue
            # standardize columns to SIAMESE_INPUT_DIM
            Xs = standardize_seq(X, SIAMESE_INPUT_DIM)
            if Xs is None or Xs.size == 0:
                continue
            seq_list.append(Xs.astype(float))
            if uid not in label_map:
                label_map[uid] = next_label
                next_label += 1
            labels.append(label_map[uid])

    total_samples = len(seq_list)
    print(
        f"[train_user] Collected total_samples={total_samples} from {len(candidate_users)} users")

    rows = []
    if total_samples > 0:
        feat_dim = SIAMESE_INPUT_DIM
        seq_len = max([s.shape[0] for s in seq_list])
        for s in seq_list:
            # ensure columns standardized (defensive)
            s = standardize_seq(s, feat_dim)
            if s.shape[1] != feat_dim:
                # skip malformed
                print("⚠ Skipping sequence with unexpected width:", s.shape)
                continue
            if s.shape[0] < seq_len:
                pad_n = seq_len - s.shape[0]
                pad = np.zeros((pad_n, feat_dim), dtype=float)
                s_p = np.vstack([s, pad])
            else:
                s_p = s[:seq_len, :]
            rows.append(sanitize_array(s_p.flatten()))

    # augmentation helper
    def augment_sample(vec, n_aug=3, jitter_scale=0.02):
        out = []
        for _ in range(n_aug):
            noise = np.random.normal(loc=0.0, scale=np.maximum(
                np.abs(vec) * jitter_scale, 1e-3), size=vec.shape)
            aug = vec + noise
            aug = np.nan_to_num(aug, nan=0.0, posinf=1e6, neginf=-1e6)
            out.append(aug)
        return out

    if len(rows) >= 20:
        training_rows = rows
        training_labels = labels
        used_augmentation = False
    elif len(rows) >= 8 or force:
        used_augmentation = True
        training_rows = list(rows)
        training_labels = list(labels)
        target = max(60, len(rows) * 6)
        idx = 0
        while len(training_rows) < target:
            vec = rows[idx % len(rows)]
            lab = labels[idx % len(rows)]
            augs = augment_sample(vec, n_aug=3, jitter_scale=0.03)
            for a in augs:
                training_rows.append(a)
                training_labels.append(lab)
                if len(training_rows) >= target:
                    break
            idx += 1
        print(
            f"[train_user] Augmented {len(rows)} -> {len(training_rows)} samples for training")
    else:
        training_rows = []
        training_labels = []
        used_augmentation = False
        print("[train_user] Not enough global samples to train siamese (proceeding to build user gallery only)")

    model = None
    trained = False
    if len(training_rows) >= 1 and len(set(training_labels)) >= 2:
        feat_dim = SIAMESE_INPUT_DIM
        seq_len = max(1, max([r.size // feat_dim for r in training_rows]))
        dataset = KeystrokeDataset(
            training_rows, training_labels, seq_len=seq_len, feat_dim=feat_dim)
        batch_size = min(len(dataset), batch_p * batch_k)
        dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

        model = SiameseTCN(SIAMESE_INPUT_DIM, SIAMESE_CHANNELS,
                           SIAMESE_EMB_DIM, SIAMESE_KERNEL, SIAMESE_DROPOUT)
        model.to(DEVICE)
        optimizer = torch.optim.Adam(
            model.parameters(), lr=lr, weight_decay=1e-5)

        model.train()
        for epoch in range(epochs):
            total_loss = 0.0
            nbatch = 0
            for batch_x, batch_y in dataloader:
                batch_x = batch_x.to(DEVICE)
                batch_y = batch_y.to(DEVICE)
                emb = model(batch_x)
                triplets = batch_all_triplet_mining(
                    emb, batch_y, margin=TRIPLET_MARGIN)
                loss = triplet_loss_from_indices(
                    emb, triplets, margin=TRIPLET_MARGIN)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                total_loss += float(loss.item())
                nbatch += 1
            avg_loss = total_loss / max(1, nbatch)
            print(
                f"[Siamese train] Epoch {epoch+1}/{epochs} avg_loss={avg_loss:.5f}")

        try:
            torch.save(model.state_dict(), SIAMESE_PATH)
            trained = True
            print("✅ Siamese model saved ->", SIAMESE_PATH)
        except Exception as e:
            print("⚠ Failed saving siamese model:", e)

    # Build gallery for requested user_id (use available sessions)
    gallery = []
    sess_ids = keystroke_col.distinct("session_id", {"user_id": user_id})
    sess_use = sess_ids[-min_sessions:] if len(
        sess_ids) >= min_sessions else sess_ids

    if trained or os.path.exists(SIAMESE_PATH):
        if model is None:
            try:
                model = load_siamese_model()
            except Exception as e:
                print("⚠ Could not load siamese model for gallery creation:", e)
                model = None

    for s in sess_use:
        evs = list(keystroke_col.find({"session_id": s, "user_id": user_id}))
        if not evs:
            continue
        if model is not None:
            try:
                emb = compute_embedding_from_events(evs, model=model)
                gallery.append(emb)
            except Exception as e:
                print(f"⚠ embedding failed for session {s}: {e}")
                continue
        else:
            break

    siamese_result = {"built": False}
    if gallery:
        k_max = 10
        gallery = gallery[-k_max:]
        centroid = list(np.mean(np.array(gallery, dtype=float), axis=0))
        users_col.update_one({"userId": user_id}, {
                             "$set": {"siamese_gallery": gallery, "siamese_centroid": centroid}})
        siamese_result = {"built": True, "gallery_size": len(gallery)}
        print(
            f"✅ Built/updated siamese gallery for {user_id} size={len(gallery)}")
        try:
            thr, n_scores, scores_list, sigma_used = compute_and_store_siamese_threshold(
                user_id, gallery, model)
            if thr is not None:
                siamese_result["threshold"] = thr
                siamese_result["n_scores"] = n_scores
                siamese_result["sigma"] = sigma_used
                print(
                    f"🎯 Stored siamese threshold={thr} computed from {n_scores} genuine scores (sigma={sigma_used})")
        except Exception as e:
            print("⚠ compute_and_store_siamese_threshold failed:", e)
    else:
        siamese_result = {
            "built": False, "reason": "no embeddings computed (insufficient model or sessions)"}
        print(
            f"ℹ Could not build siamese gallery for {user_id}: {siamese_result['reason']}")

    if not trained and len(training_rows) == 0:
        return {"status": "ok", "message": "Not enough global samples to train siamese. Built user gallery if possible.", "siamese_result": siamese_result, "total_samples": total_samples}

    return {"status": "ok", "message": "Siamese training (or augmented training) completed and user gallery built (if possible).", "siamese_result": siamese_result, "trained": trained, "total_samples": total_samples, "used_augmentation": used_augmentation}


@app.post("/api/update_model")
async def update_model(request: Request):
    data = await request.json()
    user_id = data.get("user_id")
    session_id = data.get("session_id")
    window = int(data.get("window", 10))
    if not user_id or not session_id:
        return {"status": "error", "message": "user_id and session_id required"}

    all_sessions = list(keystroke_col.distinct(
        "session_id", {"user_id": user_id}))
    if session_id not in all_sessions:
        all_sessions.append(session_id)
    recent_sessions = all_sessions[-window:]

    if not PT_AVAILABLE:
        return {"status": "error", "message": "PyTorch not available on server."}
    try:
        model = load_siamese_model()
    except Exception as e:
        print("⚠ Could not load siamese model:", e)
        return {"status": "error", "message": "Siamese model load failed"}

    gallery = []
    for s in recent_sessions:
        evs = list(keystroke_col.find({"session_id": s, "user_id": user_id}))
        if not evs:
            continue
        try:
            emb = compute_embedding_from_events(evs, model=model)
            gallery.append(emb)
        except Exception as e:
            print(f"⚠ embedding failed for session {s}: {e}")
            continue

    if not gallery:
        return {"status": "error", "message": "No embeddings computed from recent sessions"}

    k_max = 10
    gallery = gallery[-k_max:]
    centroid = list(np.mean(np.array(gallery, dtype=float), axis=0))
    users_col.update_one({"userId": user_id}, {
                         "$set": {"siamese_gallery": gallery, "siamese_centroid": centroid}})
    print(f"🔁 Updated siamese gallery for {user_id}, size={len(gallery)}")

    siamese_updated = False
    siamese_threshold = None
    try:
        thr, n_scores, scores_list, sigma_used = compute_and_store_siamese_threshold(
            user_id, gallery, model, sigma_override=None)
        if thr is not None:
            siamese_updated = True
            siamese_threshold = thr
            print(
                f"🎯 Stored siamese threshold={thr} computed from {n_scores} genuine scores (sigma={sigma_used})")
    except Exception as e:
        print("⚠ compute_and_store_siamese_threshold during update_model failed:", e)

    return {"status": "ok", "message": f"Updated siamese gallery for {user_id}", "gallery_size": len(gallery), "siamese_updated": siamese_updated, "siamese_threshold": siamese_threshold}


@app.get("/api/balance/{username}")
def get_balance(username: str):
    user = users_col.find_one({"userId": username})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"username": username, "balance": float(user.get("balance", 0.0))}


@app.post("/api/transfer")
async def transfer_funds(request: Request):
    data = await request.json()
    sender = data.get("sender")
    recipient = data.get("recipient")
    amount = float(data.get("amount", 0))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid transfer amount")
    sender_user = users_col.find_one({"userId": sender})
    receiver_user = users_col.find_one({"userId": recipient})
    if not sender_user or not receiver_user:
        raise HTTPException(
            status_code=404, detail="Invalid sender or recipient")
    sender_balance = float(sender_user.get("balance", 0))
    if sender_balance < amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")
    users_col.update_one({"_id": sender_user["_id"]}, {
                         "$set": {"balance": sender_balance - amount}})
    users_col.update_one({"_id": receiver_user["_id"]}, {
                         "$set": {"balance": float(receiver_user.get('balance', 0)) + amount}})
    txn = {"sender": sender, "recipient": recipient,
           "amount": amount, "timestamp": datetime.utcnow().isoformat()}
    transactions_col.insert_one(txn)
    return {"message": f"Transferred ₹{amount:.2f} to {recipient}", "sender_balance": sender_balance - amount}


@app.get("/api/transactions/{username}")
def get_transactions(username: str):
    txns = list(transactions_col.find(
        {"$or": [{"sender": username}, {"recipient": username}]}))
    for t in txns:
        t["_id"] = str(t["_id"])
    return {"transactions": txns}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print("❌ Unhandled exception:", exc, traceback.format_exc())
    return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})
