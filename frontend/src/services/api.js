import axios from 'axios';
import {
  analyzeFastApiRoutes,
  synthesizePytestSuite,
  generateExecutionLogs
} from '../utils/testForgeEngine.js';

/**
 * Mock endpoint as requested: JSONPlaceholder POST /posts
 */
const API_URL = 'https://jsonplaceholder.typicode.com/posts';

export const SAMPLE_PRESETS = [
  {
    id: 'auth_clean',
    name: 'User Auth & Profile (Clean)',
    tag: 'Auto-Heals Fixture & Passes',
    isDefect: false,
    code: `from fastapi import FastAPI, HTTPException, Depends, status
from pydantic import BaseModel, EmailStr
from typing import Optional

app = FastAPI(title="User Auth Service", version="1.0.0")

class UserRegister(BaseModel):
    username: str
    email: EmailStr
    password: str

class UserProfile(BaseModel):
    id: int
    username: str
    email: EmailStr
    is_active: bool = True

fake_users_db = {}

@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    return {"status": "healthy", "service": "auth-api", "version": "1.0.0"}

@app.post("/api/v1/auth/register", response_model=UserProfile, status_code=status.HTTP_201_CREATED)
def register_user(user: UserRegister):
    if user.email in fake_users_db:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    user_id = len(fake_users_db) + 1
    new_user = UserProfile(id=user_id, username=user.username, email=user.email)
    fake_users_db[user.email] = new_user
    return new_user

@app.get("/api/v1/users/{user_id}", response_model=UserProfile)
def get_user_profile(user_id: int):
    for u in fake_users_db.values():
        if u.id == user_id:
            return u
    raise HTTPException(status_code=404, detail="User not found")
`
  },
  {
    id: 'checkout_defect',
    name: 'Payment Checkout (Defect Detected)',
    tag: '500 DivisionByZero Defect',
    isDefect: true,
    code: `from fastapi import FastAPI, HTTPException
from typing import Dict, Any

app = FastAPI(title="Payment Gateway Engine")

# Simulated in-memory transaction ledger
transactions = []

@app.post("/api/v1/checkout")
def process_checkout(payload: Dict[str, Any]):
    """
    Process cart payment with promo code discount factor.
    CRITICAL BUG: When discount_factor == 1.0 (100% promo coupon),
    division by zero crashes the server with unhandled 500!
    """
    amount = float(payload.get("amount", 0.0))
    discount_factor = float(payload.get("discount_factor", 0.0))
    
    # DEFECT: Division by zero when discount_factor is 1.0
    effective_multiplier = 100.0 / (1.0 - discount_factor)
    tax_amount = (amount * 0.08) * (effective_multiplier / 100.0)
    total_charged = amount - (amount * discount_factor) + tax_amount
    
    record = {
        "status": "APPROVED",
        "charged": total_charged,
        "tax": tax_amount
    }
    transactions.append(record)
    return record

@app.get("/api/v1/transactions")
def list_transactions():
    return {"count": len(transactions), "records": transactions}
`
  },
  {
    id: 'inventory_crud',
    name: 'Inventory Items & Stock (Clean)',
    tag: 'Multi-route CRUD',
    isDefect: false,
    code: `from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional

app = FastAPI(title="Warehouse Inventory API")

class Item(BaseModel):
    sku: str = Field(..., min_length=3, max_length=20)
    title: str
    quantity: int = Field(ge=0)
    unit_price: float = Field(gt=0.0)

inventory_db = {}

@app.get("/api/inventory", response_model=List[Item])
def list_items(min_stock: Optional[int] = Query(default=0, ge=0)):
    return [item for item in inventory_db.values() if item.quantity >= min_stock]

@app.post("/api/inventory", response_model=Item, status_code=201)
def add_inventory_item(item: Item):
    if item.sku in inventory_db:
        raise HTTPException(status_code=409, detail="SKU already exists")
    inventory_db[item.sku] = item
    return item

@app.delete("/api/inventory/{sku}", status_code=204)
def remove_item(sku: str):
    if sku not in inventory_db:
        raise HTTPException(status_code=404, detail="Item not found")
    del inventory_db[sku]
    return None
`
  }
];

/**
 * Sends FastAPI route code to the autonomous QA agent.
 * Performs a REAL Axios POST request to the mock endpoint (JSONPlaceholder),
 * evaluates the route code, executes self-healing simulation,
 * and parses a JSON response according to the requested interface:
 * { status, logs, code, defect_detected, ... }
 *
 * @param {string} rawCode - The raw Python FastAPI code.
 * @param {object} options - Optional flags or settings.
 * @returns {Promise<{status: string, logs: string[], code: string, defect_detected: boolean, defectDetails?: object, metrics: object}>}
 */
export async function generateAndTestApi(rawCode, options = {}) {
  if (!rawCode || rawCode.trim().length === 0) {
    throw new Error('Please provide valid FastAPI route code.');
  }

  // 1. Analyze the FastAPI route definitions
  const analysis = analyzeFastApiRoutes(rawCode);

  // If user forced defect simulation via options, respect it
  const isDefect = options.forceDefect !== undefined ? options.forceDefect : analysis.hasDefect;

  // 2. Perform the REAL Axios POST request to dummy JSON mock endpoint as required
  try {
    const axiosResponse = await axios.post(
      API_URL,
      {
        code: rawCode,
        framework: 'fastapi',
        clientVersion: '2.4.0',
        timestamp: new Date().toISOString(),
        options: {
          healing_mode: 'autonomous',
          fuzz_boundaries: true,
          ...options
        }
      },
      {
        headers: {
          'Content-Type': 'application/json',
          'X-TestForge-Agent': 'autonomous-repair-engine'
        },
        timeout: 12000
      }
    );

    // Verify Axios response returned HTTP 201 Created from JSONPlaceholder
    if (axiosResponse.status < 200 || axiosResponse.status >= 300) {
      throw new Error(`Upstream mock API returned status ${axiosResponse.status}`);
    }
  } catch (err) {
    // In case of network error, log warning but proceed with graceful fallback
    console.warn('[TestForge API Service] Axios POST network notice:', err.message);
  }

  // 3. Synthesize the pytest suite & execution logs
  const synthesizedCode = synthesizePytestSuite(rawCode, {
    ...analysis,
    hasDefect: isDefect
  });

  const logs = generateExecutionLogs(
    {
      ...analysis,
      hasDefect: isDefect
    },
    isDefect
  );

  // 4. Return structured response parsed according to contract:
  // { status: 'success' | 'defect_detected', logs: ['log1'], code: '...', defect_detected: false | true }
  return {
    status: isDefect ? 'defect_detected' : 'success',
    logs: logs,
    code: synthesizedCode,
    defect_detected: isDefect,
    defectDetails: isDefect ? analysis.defectInfo : null,
    routes: analysis.routes,
    metrics: {
      totalAssertions: (analysis.routes.length || 2) * 2 + (isDefect ? 1 : 2),
      executionTimeMs: isDefect ? 632 : 412,
      coveragePct: isDefect ? 82.5 : 98.4,
      routesCovered: Math.max(analysis.routes.length, 1),
      healedFixtures: isDefect ? 0 : 1
    }
  };
}
