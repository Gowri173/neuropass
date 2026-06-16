from fastapi import APIRouter, HTTPException, Request
from pymongo import MongoClient
from bson import ObjectId
import datetime

# ✅ Connect to MongoDB
client = MongoClient("mongodb://localhost:27017/")
db = client["neuropass"]
users_col = db["users"]
transactions_col = db["transactions"]

router = APIRouter()

# -------------------------------
# 📊 Utility functions
# -------------------------------


def get_user(username: str):
    user = users_col.find_one({"username": username})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def record_transaction(user_id, txn_type, amount, description):
    txn = {
        "user_id": str(user_id),
        "type": txn_type,   # 'credit' or 'debit'
        "amount": float(amount),
        "description": description,
        "timestamp": datetime.datetime.now().isoformat(),
    }
    transactions_col.insert_one(txn)

# -------------------------------
# 🧾 1. Get Balance
# -------------------------------


@router.get("/balance/{username}")
def get_balance(username: str):
    user = get_user(username)
    return {"username": username, "balance": user.get("balance", 0.0)}

# -------------------------------
# 💸 2. Transfer Funds
# -------------------------------


@router.post("/transfer")
async def transfer_funds(request: Request):
    data = await request.json()
    sender = data.get("sender")
    recipient = data.get("recipient")
    amount = float(data.get("amount", 0))

    if amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid transfer amount")

    sender_user = get_user(sender)
    receiver_user = get_user(recipient)

    sender_balance = float(sender_user.get("balance", 0))
    if sender_balance < amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    # ✅ Perform transfer
    new_sender_balance = sender_balance - amount
    new_receiver_balance = float(receiver_user.get("balance", 0)) + amount

    users_col.update_one({"_id": sender_user["_id"]}, {
                         "$set": {"balance": new_sender_balance}})
    users_col.update_one({"_id": receiver_user["_id"]}, {
                         "$set": {"balance": new_receiver_balance}})

    # ✅ Record transactions
    record_transaction(sender_user["_id"], "debit",
                       amount, f"Sent to {recipient}")
    record_transaction(
        receiver_user["_id"], "credit", amount, f"Received from {sender}")

    return {
        "message": f"Successfully transferred ₹{amount:.2f} to {recipient}",
        "sender_balance": new_sender_balance,
        "receiver_balance": new_receiver_balance
    }

# -------------------------------
# 📜 3. Get Transaction History
# -------------------------------


@router.get("/transactions/{username}")
def get_transactions(username: str):
    user = get_user(username)
    txns = list(transactions_col.find({"user_id": str(user["_id"])}))
    for txn in txns:
        txn["_id"] = str(txn["_id"])
    return {"transactions": txns}
