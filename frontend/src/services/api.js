import axios from 'axios';

// The dropdown templates for the UI
export const SAMPLE_PRESETS = [
  {
    id: "auth-clean",
    name: "User Auth & Profile (Clean)",
    code: `from fastapi import FastAPI, HTTPException, status\nfrom pydantic import BaseModel, EmailStr\n\napp = FastAPI(title="User Auth Service")\n\nclass UserRegister(BaseModel):\n    username: str\n    email: EmailStr\n    password: str\n\n@app.post("/register", status_code=status.HTTP_201_CREATED)\ndef register_user(user: UserRegister):\n    return {"message": f"User {user.username} created successfully", "id": 1}`
  },
  {
    id: "checkout-defect",
    name: "Payment Checkout (Defect Detected)",
    code: `from fastapi import FastAPI, HTTPException\nfrom pydantic import BaseModel\n\napp = FastAPI()\n\nclass CheckoutPayload(BaseModel):\n    cart_total: float\n    discount_factor: float\n\n@app.post("/api/v1/checkout")\ndef process_checkout(payload: CheckoutPayload):\n    # CRITICAL BUG: When discount_factor == 1.0 (100% promo),\n    # division by zero occurs below.\n    final_price = payload.cart_total / (1.0 - payload.discount_factor)\n    return {"amount_charged": final_price}`
  }
];

// Pointing directly to your local FastAPI server
const API_URL = 'http://localhost:8000/generate-tests';

export const VALID_MODES = ['standard', 'adversarial'];

// Renamed to match exactly what App.jsx is importing
export const generateAndTestApi = async (codeSnippet, mode = 'standard') => {
  if (!codeSnippet || codeSnippet.trim() === "") {
    throw new Error("Code snippet cannot be empty.");
  }

  const selectedMode = VALID_MODES.includes(mode) ? mode : 'standard';

  try {
    // Send the raw Python code and mode to our AI Orchestrator
    const response = await axios.post(API_URL, {
      code: codeSnippet,
      mode: selectedMode,
    });

    // Return the response dict exactly as FastAPI sends it
    return response.data;

  } catch (error) {
    console.error("Backend Error:", error);
    // Preserve structured backend errors so the UI can display an honest
    // failed/error state instead of treating every non-2xx response as a defect.
    if (error.response?.data?.status) {
      return error.response.data;
    }
    throw new Error(
      error.response?.data?.detail ||
      "Failed to connect to the backend engine. Is FastAPI running?"
    );
  }
};
