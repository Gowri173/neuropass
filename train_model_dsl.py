import os
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
import joblib

# Create models folder if missing
os.makedirs("models", exist_ok=True)

# Load dataset (safe relative path)
df = pd.read_csv("data/DSL-StrongPasswordData.csv")

# Features & target
X = df.drop(columns=["subject", "sessionIndex", "rep"])
y = df["subject"]

# Train-test split
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.3, random_state=42, stratify=y
)

# Train model
model = RandomForestClassifier(n_estimators=300, random_state=42, n_jobs=-1)
model.fit(X_train, y_train)

# Evaluate
y_pred = model.predict(X_test)
print(f"✅ Accuracy: {accuracy_score(y_test, y_pred):.4f}")
print("📊 Classification Report:")
print(classification_report(y_test, y_pred))

# Save model
joblib.dump(model, "models/randomforest.pkl")
print("🎉 Model saved successfully → models/randomforest.pkl")
