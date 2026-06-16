// ✅ src/BankingDashboard.js — Final Stable Version (Logout & Redirect Fix)
import React, { useState, useEffect } from "react";
import styled, { keyframes } from "styled-components";
import { useNavigate } from "react-router-dom";

/* ---------- Animations ---------- */
const fadeIn = keyframes`
  from { opacity: 0; transform: translateY(15px); }
  to { opacity: 1; transform: translateY(0); }
`;

const glow = keyframes`
  0% { box-shadow: 0 0 5px #00ffb7, 0 0 10px #00ffb7; }
  100% { box-shadow: 0 0 15px #00b7ff, 0 0 30px #00b7ff; }
`;

/* ---------- Styled Components ---------- */
const Container = styled.div`
  min-height: 100vh;
  background: radial-gradient(circle at 20% 20%, #09101f, #04060a 70%);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 3rem 1rem;
  font-family: "Inter", sans-serif;
  color: #e6edf3;
  animation: ${fadeIn} 0.7s ease forwards;
`;

const DashboardHeader = styled.div`
  width: 100%;
  max-width: 1000px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2rem;

  @media (max-width: 600px) {
    flex-direction: column;
    gap: 1rem;
    text-align: center;
  }
`;

const WelcomeText = styled.h1`
  font-size: 1.5rem;
  font-weight: 600;
  color: #00ffb7;
  span {
    color: #00b7ff;
  }
`;

const LogoutButton = styled.button`
  padding: 10px 18px;
  border-radius: 8px;
  border: none;
  background: linear-gradient(90deg, #ff3d3d, #ff7b00);
  color: white;
  font-weight: 600;
  cursor: pointer;
  transition: 0.3s;
  &:hover {
    transform: scale(1.05);
    box-shadow: 0 0 15px #ff7b00aa;
  }
`;

const CardGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: 2rem;
  width: 100%;
  max-width: 1000px;
`;

const Card = styled.div`
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  padding: 2rem;
  text-align: center;
  box-shadow: 0 0 25px rgba(0, 200, 255, 0.1);
  transition: all 0.3s ease;
  backdrop-filter: blur(10px);
  animation: ${fadeIn} 0.8s ease both;

  &:hover {
    transform: translateY(-3px);
    border-color: #00ffb755;
    animation: ${glow} 1.5s alternate infinite ease-in-out;
  }

  @media (max-width: 480px) {
    padding: 1.5rem;
  }
`;

const Title = styled.h2`
  color: #00b7ff;
  margin-bottom: 1.2rem;
  font-size: 1.3rem;
`;

const Balance = styled.h1`
  font-size: 2.5rem;
  color: #00ffb7;
  text-shadow: 0 0 10px #00ffb7aa;
`;

const Input = styled.input`
  width: 100%;
  padding: 12px;
  margin-bottom: 12px;
  border-radius: 10px;
  border: none;
  background: #10131a;
  color: #e6edf3;
  font-size: 15px;
  transition: 0.3s;

  &:focus {
    outline: 2px solid #00ffb7;
    background: #0b0f18;
  }
`;

const Button = styled.button`
  width: 100%;
  padding: 12px;
  border-radius: 10px;
  border: none;
  background: linear-gradient(90deg, #00b7ff, #00ffb7);
  color: white;
  font-weight: 600;
  cursor: pointer;
  transition: 0.3s;

  &:hover {
    transform: scale(1.03);
    box-shadow: 0 0 15px #00b7ff99;
  }

  &:disabled {
    background: #333;
    cursor: not-allowed;
  }
`;

const Message = styled.p`
  margin-top: 1rem;
  font-weight: 500;
  color: ${({ $success }) => ($success ? "#00ffb7" : "#ff4d4f")};
`;

const TransactionList = styled.div`
  text-align: left;
  background: rgba(0, 255, 183, 0.05);
  padding: 1rem;
  border-radius: 10px;
  max-height: 260px;
  overflow-y: auto;

  &::-webkit-scrollbar {
    width: 8px;
  }
  &::-webkit-scrollbar-thumb {
    background-color: #00b7ff88;
    border-radius: 10px;
  }
`;

const Transaction = styled.div`
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding: 10px 0;
  font-size: 0.9rem;
  line-height: 1.4;
  b {
    color: #00ffb7;
  }
`;

/* ---------- Component ---------- */
export default function BankingDashboard({ user }) {
  const [balance, setBalance] = useState(0);
  const [recipient, setRecipient] = useState("");
  const [amount, setAmount] = useState("");
  const [transactions, setTransactions] = useState([]);
  const [message, setMessage] = useState("");
  const navigate = useNavigate();

  const currentUser = user || localStorage.getItem("neuropass_user");

  useEffect(() => {
    if (!currentUser) {
      navigate("/", { replace: true });
      return;
    }
  }, [currentUser, navigate]);

  const fetchData = async () => {
    if (!currentUser) return;
    try {
      const [balRes, txRes] = await Promise.all([
        fetch(`http://localhost:8000/api/balance/${currentUser}`),
        fetch(`http://localhost:8000/api/transactions/${currentUser}`),
      ]);
      const balData = await balRes.json();
      const txData = await txRes.json();
      setBalance(balData.balance || 0);
      setTransactions(txData.transactions || []);
    } catch (err) {
      console.error("Fetch error:", err);
    }
  };

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentUser]);

  const handleTransfer = async () => {
    setMessage("⏳ Processing transfer...");
    try {
      const res = await fetch("http://localhost:8000/api/transfer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sender: currentUser,
          recipient,
          amount: parseFloat(amount),
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setMessage(`✅ ${data.message}`);
        setBalance(data.sender_balance);
        setRecipient("");
        setAmount("");
        fetchData();
      } else {
        setMessage(`❌ ${data.detail || "Transfer failed"}`);
      }
    } catch (err) {
      setMessage(`❌ Error: ${err.message}`);
    }
  };

  /* --- Logout --- */
  const handleLogout = () => {
    localStorage.removeItem("neuropass_user");
    sessionStorage.removeItem("auth_redirected");
    sessionStorage.removeItem("protected_redirected");
    navigate("/", { replace: true });
  };

  return (
    <Container>
      <DashboardHeader>
        <WelcomeText>
          🧠 Welcome, <span>{currentUser}</span>
        </WelcomeText>
        <LogoutButton onClick={handleLogout}>Logout</LogoutButton>
      </DashboardHeader>

      <CardGrid>
        <Card>
          <Title>💰 Account Balance</Title>
          <Balance>₹{balance.toFixed(2)}</Balance>
        </Card>

        <Card>
          <Title>💸 Transfer Money</Title>
          <Input
            placeholder="Recipient Username"
            value={recipient}
            onChange={(e) => setRecipient(e.target.value)}
          />
          <Input
            placeholder="Amount (₹)"
            type="number"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
          <Button disabled={!recipient || !amount} onClick={handleTransfer}>
            Send Money
          </Button>
          {message && <Message $success={message.startsWith("✅")}>{message}</Message>}
        </Card>

        <Card>
          <Title>📜 Transaction History</Title>
          <TransactionList>
            {transactions.length === 0 && <p>No transactions yet.</p>}
            {transactions.map((txn) => (
              <Transaction key={txn._id}>
                <b>{txn.sender}</b> → <b>{txn.recipient}</b> : ₹{txn.amount}
                <br />
                <small style={{ color: "#888" }}>
                  {new Date(txn.timestamp).toLocaleString()}
                </small>
              </Transaction>
            ))}
          </TransactionList>
        </Card>
      </CardGrid>
    </Container>
  );
}
