import numpy as np
import pandas as pd


def extract_mouse_features(events):
    """
    Extracts mouse dynamics features from event stream.
    Each event: { userId, type, x, y, ts }
    """
    events = sorted(events, key=lambda e: e["ts"])
    df = pd.DataFrame(events)
    if len(df) < 5:
        return pd.DataFrame([{
            "avg_speed": 0,
            "max_speed": 0,
            "path_efficiency": 0,
            "click_density": 0
        }])

    # Δt, Δx, Δy
    df["dx"] = df["x"].diff()
    df["dy"] = df["y"].diff()
    df["dt"] = df["ts"].diff()
    df["speed"] = np.sqrt(df["dx"]**2 + df["dy"]**2) / (df["dt"] / 1000)
    avg_speed = df["speed"].mean()
    max_speed = df["speed"].max()

    # Path efficiency (direct / total distance)
    total_dist = df["speed"].sum() * (df["dt"].mean() / 1000)
    direct_dist = np.sqrt((df["x"].iloc[-1] - df["x"].iloc[0])**2 +
                          (df["y"].iloc[-1] - df["y"].iloc[0])**2)
    path_efficiency = direct_dist / total_dist if total_dist else 0

    # Click density
    clicks = len(df[df["type"].isin(["mousedown", "mouseup"])])
    click_density = clicks / len(df)

    features = pd.DataFrame([{
        "avg_speed": avg_speed,
        "max_speed": max_speed,
        "path_efficiency": path_efficiency,
        "click_density": click_density
    }])
    return features
