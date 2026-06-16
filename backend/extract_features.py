# extract_features.py
import numpy as np
import pandas as pd
import os
import joblib
from typing import List, Tuple, Optional, Dict

"""
📄 extract_features.py (upgraded)
------------------------------------------
- Backwards-compatible extract_features(events) -> pandas.DataFrame
  (keeps the original DSL flattened single-row output used by main.py)
- New helpers for sequence-oriented pipelines:
    - extract_sequence_features(events, max_seq_len=None, feat_set='full')
    - events_to_keystrokes(events)
- Augmentation utilities via KeystrokeAugmenter
- Robust handling of performance timestamps (perf_ts) and wall timestamps (ts/wall_ts)
"""

# ---------------- DSL-style column names (legacy compatibility) ----------------
DSL_COLUMNS = [
    # Hold times (key down → key up) - up to 10 positions (pad/truncate)
    "H.period", "H.t", "H.i", "H.s", "H.e", "H.c", "H.r", "H.a", "H.n", "H.Return",
    # Down-Down times (adjacent) - up to 9
    "DD.period.t", "DD.t.i", "DD.i.s", "DD.s.e", "DD.e.c", "DD.c.r", "DD.r.a", "DD.a.n", "DD.n.Return",
    # Up-Down times (adjacent) - up to 9
    "UD.period.t", "UD.t.i", "UD.i.s", "UD.s.e", "UD.e.c", "UD.c.r", "UD.r.a", "UD.a.n", "UD.n.Return"
]

# Try loading model for alignment (legacy)
MODEL_PATH = os.path.join(os.path.dirname(
    __file__), "../models/randomforest.pkl")
_model_for_alignment = None
if os.path.exists(MODEL_PATH):
    try:
        _model_for_alignment = joblib.load(MODEL_PATH)
        print(f"✅ Model loaded for feature alignment ({MODEL_PATH})")
    except Exception as e:
        print(f"⚠️ Warning: Could not load model for feature alignment: {e}")


# ---------------- Utility: normalize input events & sort ----------------
def _normalize_and_sort_events(events: List[dict]) -> List[dict]:
    """
    Ensure each event has a timestamp field and return them sorted by a high-resolution clock if available.
    Accepts events with keys: perf_ts (recommended), ts, wall_ts. Prefers perf_ts if present.
    """
    normalized = []
    for e in events:
        ev = dict(e)  # shallow copy
        # Accept multiple timestamp fields; prefer perf_ts (high-res epoch if provided)
        if "perf_ts" in ev and ev["perf_ts"] is not None:
            ev["_ts"] = float(ev["perf_ts"])
        elif "ts" in ev and ev["ts"] is not None:
            ev["_ts"] = float(ev["ts"])
        elif "wall_ts" in ev and ev["wall_ts"] is not None:
            ev["_ts"] = float(ev["wall_ts"])
        else:
            # fallback to current time
            ev["_ts"] = float(pd.Timestamp.now().timestamp() * 1000.0)
        normalized.append(ev)
    # sort by chosen timestamp
    normalized = sorted(normalized, key=lambda x: x.get("_ts", 0.0))
    return normalized


# ---------------- Pair down/up events into keystroke records ----------------
def events_to_keystrokes(events: List[dict]) -> List[dict]:
    """
    Convert interleaved down/up events to keystroke records:
    returns list of dicts: { key, down_ts, up_ts (or None if missing), duration (up-down) if available }
    Robustly handles missing ups/downs by skipping incomplete pairs or inferring small default values.
    """
    evs = _normalize_and_sort_events(events)
    # pending downs: list of tuples (key, down_ts, event_meta)
    pending = []
    keystrokes = []

    for e in evs:
        t = e.get("_ts")
        typ = e.get("type") or e.get("event") or e.get("evt")
        key = e.get("code") or e.get("key") or e.get(
            "keyCode") or e.get("key_name") or "UNKN"
        if typ is None:
            continue
        typ = typ.lower()
        if typ in ("keydown", "down"):
            # record the down; include repeat info
            pending.append({"key": key, "down_ts": t, "meta": e})
        elif typ in ("keyup", "up"):
            # find the earliest pending down for the same key
            idx = next((i for i, p in enumerate(
                pending) if p["key"] == key), None)
            if idx is not None and idx < len(pending):
                p = pending.pop(idx)
                ks = {"key": key, "down_ts": p["down_ts"], "up_ts": t}
                ks["duration"] = ks["up_ts"] - ks["down_ts"]
                keystrokes.append(ks)
            else:
                # orphan up - ignore or create small synthetic down (skip here)
                continue

    # Optionally: any pending downs left without up -> drop or infer
    # We'll drop them (safer) - they likely indicate incomplete capture.
    return keystrokes


# ---------------- Sequence feature extraction ----------------
def extract_sequence_features(events: List[dict], max_seq_len: Optional[int] = None, feat_set: str = "full") -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """
    Convert raw events into a sequence array of shape (seq_len, feat_dim).
    Returns:
      X: np.ndarray (seq_len, feat_dim)
      mask: np.ndarray (seq_len,) with 1 for valid positions, 0 for pads (or None if no padding)
    Feature set 'full' includes: [dwell, dd (to prev down), du (down - prev up), uu (up - prev up), key_index]
    For backward compatibility main.py's old pipeline expects a single-row DataFrame, so use extract_features() wrapper.
    """
    keystrokes = events_to_keystrokes(events)
    if not keystrokes:
        # return minimal padded array
        if max_seq_len is None:
            return np.zeros((1, 4), dtype=float), np.array([1], dtype=int)
        else:
            return np.zeros((max_seq_len, 4), dtype=float), np.concatenate([np.ones(1, dtype=int), np.zeros(max_seq_len - 1, dtype=int)])

    # build primitive arrays
    n = len(keystrokes)
    # dwell: up_ts - down_ts (already computed)
    dwells = np.array([max(0.0, k.get("duration", 0.0))
                      for k in keystrokes], dtype=float)
    downs = np.array([k["down_ts"] for k in keystrokes], dtype=float)
    ups = np.array([k["up_ts"] for k in keystrokes], dtype=float)
    keys = [k["key"] for k in keystrokes]

    # dd: down_i - down_{i-1} (first -> 0)
    dd = np.zeros_like(downs)
    dd[1:] = downs[1:] - downs[:-1]

    # du: down_i - up_{i-1} (first -> 0)
    du = np.zeros_like(downs)
    if len(ups) >= 1:
        du[1:] = downs[1:] - ups[:-1]

    # uu: up_i - up_{i-1}
    uu = np.zeros_like(ups)
    uu[1:] = ups[1:] - ups[:-1]

    # key indexing (simple mapping) - keep small vocabulary
    key_vocab = {}
    kv_next = 1  # reserve 0 for unknown / pad
    key_idx = []
    for k in keys:
        if k not in key_vocab:
            key_vocab[k] = kv_next
            kv_next += 1
        key_idx.append(key_vocab[k])
    key_idx = np.array(key_idx, dtype=float)

    # Assemble feature matrix: [dwell, dd, du, uu, key_idx]
    # Optionally expand with additional windows/statistics if feat_set == 'full'
    feat_list = [dwells, dd, du, uu, key_idx]
    X = np.vstack(feat_list).T  # shape (n, feat_dim)

    # If max_seq_len specified, pad/truncate and produce mask
    if max_seq_len is not None:
        if n >= max_seq_len:
            X = X[:max_seq_len, :]
            mask = np.ones(max_seq_len, dtype=int)
        else:
            pad_n = max_seq_len - n
            pad = np.zeros((pad_n, X.shape[1]), dtype=float)
            X = np.vstack([X, pad])
            mask = np.concatenate(
                [np.ones(n, dtype=int), np.zeros(pad_n, dtype=int)])
        return X, mask

    return X, np.ones(X.shape[0], dtype=int)


# ---------------- Legacy flattened DSL-style feature extractor ----------------
def extract_features(events: List[dict]) -> pd.DataFrame:
    """
    Backwards-compatible function used across the codebase.
    Produces a single-row DataFrame whose columns match DSL_COLUMNS (padded/truncated).
    This preserves existing main.py behavior where extract_features(...).values is flattened.
    """
    if not events:
        raise ValueError(
            "No keystroke events provided for feature extraction.")

    # create keystrokes and compute primitive arrays
    keystrokes = events_to_keystrokes(events)

    # compute holds, dd, ud arrays (following the original script logic)
    holds = []
    dd_times = []
    up_down_times = []

    for i, k in enumerate(keystrokes):
        holds.append(max(0.0, k.get("duration", 0.0)))
    for i in range(1, len(keystrokes)):
        dd_times.append(
            max(0.0, keystrokes[i]["down_ts"] - keystrokes[i - 1]["down_ts"]))
    # up-down: down_{i+1} - up_i
    for i in range(min(len(keystrokes) - 1, len(keystrokes))):
        if i + 1 < len(keystrokes) and i < len(keystrokes):
            diff = max(0.0, keystrokes[i + 1]
                       ["down_ts"] - keystrokes[i]["up_ts"])
            up_down_times.append(diff)

    # pad/truncate to match DSL lengths
    holds = np.pad(np.array(holds[:10], dtype=float),
                   (0, max(0, 10 - len(holds))), mode="constant")
    dd_times = np.pad(np.array(dd_times[:9], dtype=float), (0, max(
        0, 9 - len(dd_times))), mode="constant")
    up_down_times = np.pad(np.array(up_down_times[:9], dtype=float), (0, max(
        0, 9 - len(up_down_times))), mode="constant")

    features = np.concatenate([holds, dd_times, up_down_times])
    # build DataFrame
    feature_dict = {DSL_COLUMNS[i]: float(
        features[i]) for i in range(len(DSL_COLUMNS))}
    df = pd.DataFrame([feature_dict])

    # Align with loaded model if available (legacy compatibility)
    if _model_for_alignment is not None:
        try:
            if hasattr(_model_for_alignment, "feature_names_in_"):
                expected = list(_model_for_alignment.feature_names_in_)
            else:
                expected = list(df.columns)
            for col in expected:
                if col not in df.columns:
                    df[col] = 0.0
            df = df[expected]
        except Exception:
            pass

    print(f"[extract_features] Output shape: {df.shape}")
    if _model_for_alignment is not None and hasattr(_model_for_alignment, "n_features_in_"):
        print(
            f"[extract_features] Model expects: {_model_for_alignment.n_features_in_} features")
    return df


# ---------------- Augmentation utilities ----------------
class KeystrokeAugmenter:
    """
    Implements jitter (relative gaussian), simple time-warp, and key-drop augmentations.
    Usage: augmenter = KeystrokeAugmenter(); x_jittered = augmenter.jitter(X)
    """

    def __init__(self, jitter_pct: Tuple[float, float] = (0.01, 0.05), key_drop_prob: float = 0.01):
        self.jitter_pct = jitter_pct
        self.key_drop_prob = key_drop_prob

    def jitter(self, X: np.ndarray) -> np.ndarray:
        """
        Apply relative gaussian jitter to timing columns (assumes numeric columns are timing-like).
        We avoid applying jitter to the key index column (last column).
        """
        if X is None or X.size == 0:
            return X
        X = X.copy()
        seq_len, feat_dim = X.shape
        # assume last column is key index (non-timing) -> do not jitter
        timing_cols = list(range(max(0, feat_dim - 1))
                           ) if feat_dim >= 1 else list(range(feat_dim))
        # alternative heuristic: jitter all columns except integer key index (detect by small unique count)
        for j in timing_cols:
            col = X[:, j]
            scale = np.random.uniform(self.jitter_pct[0], self.jitter_pct[1])
            noise = np.random.normal(loc=0.0, scale=np.maximum(
                np.abs(col) * scale, 1e-3), size=col.shape)
            X[:, j] = col + noise
        # sanitize
        X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)
        return X

    def key_drop(self, X: np.ndarray, prob: Optional[float] = None) -> np.ndarray:
        """
        Randomly drop (remove) keystroke rows with probability prob.
        Returns reduced sequence; caller must handle padding to desired length.
        """
        if X is None or X.size == 0:
            return X
        if prob is None:
            prob = self.key_drop_prob
        mask = np.random.rand(X.shape[0]) >= prob
        if not mask.any():
            # ensure at least one remains
            idx = np.random.randint(0, X.shape[0])
            mask[idx] = True
        return X[mask]

    def time_warp(self, X: np.ndarray, max_warp: float = 0.1) -> np.ndarray:
        """
        Simple time-warp: scale a random contiguous window of time-related columns by a factor in [1-max_warp, 1+max_warp].
        Implementation assumes timing features are in columns 0..k-1 (we'll treat first 4 as timings: dwell, dd, du, uu).
        """
        if X is None or X.size == 0:
            return X
        X = X.copy()
        seq_len, feat_dim = X.shape
        # choose default timing channels to warp: first four columns if present
        n_timing = min(4, feat_dim)
        if n_timing == 0:
            return X
        # pick random window
        if seq_len <= 1:
            return X
        w = max(1, int(np.clip(np.random.randint(
            1, max(2, seq_len // 4)), 1, seq_len)))
        start = np.random.randint(0, seq_len - w + 1)
        factor = 1.0 + np.random.uniform(-max_warp, max_warp)
        # apply factor to timing columns in window
        X[start:start + w, :n_timing] = X[start:start + w, :n_timing] * factor
        # sanitize
        X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)
        return X

    def augment(self, X: np.ndarray, apply_jitter: bool = True, apply_time_warp: bool = True, apply_key_drop: bool = True) -> np.ndarray:
        """
        Apply a random combination of augmentations. Always apply jitter if enabled (helps numeric stability).
        """
        out = X.copy()
        if apply_jitter:
            out = self.jitter(out)
        if apply_time_warp and (np.random.rand() < 0.5):
            out = self.time_warp(out)
        if apply_key_drop and (np.random.rand() < 0.1):
            out = self.key_drop(out)
        return out


# ---------------- Convenience: minimal test when executed directly ----------------
if __name__ == "__main__":
    dummy_events = [
        {"type": "keydown", "key": "KeyA", "code": "KeyA",
            "perf_ts": 1000.0, "wall_ts": 1590000000000},
        {"type": "keyup", "key": "KeyA", "code": "KeyA",
            "perf_ts": 1080.0, "wall_ts": 1590000000080},
        {"type": "keydown", "key": "KeyB", "code": "KeyB",
            "perf_ts": 1100.0, "wall_ts": 1590000000100},
        {"type": "keyup", "key": "KeyB", "code": "KeyB",
            "perf_ts": 1160.0, "wall_ts": 1590000000160},
        {"type": "keydown", "key": "Return", "code": "Enter",
            "perf_ts": 1180.0, "wall_ts": 1590000000180},
        {"type": "keyup", "key": "Return", "code": "Enter",
            "perf_ts": 1250.0, "wall_ts": 1590000000250},
    ]

    df = extract_features(dummy_events)
    print(df)
    X, mask = extract_sequence_features(dummy_events, max_seq_len=8)
    print("X.shape:", X.shape, "mask:", mask)
    aug = KeystrokeAugmenter()
    print("Jittered example:\n", aug.jitter(X))
    print("Time warped:\n", aug.time_warp(X))
    print("Key dropped:\n", aug.key_drop(X))
