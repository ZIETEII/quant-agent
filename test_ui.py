from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

app = FastAPI()
app.mount("/static", StaticFiles(directory="web/static"), name="static")

@app.get("/")
async def read_item():
    return FileResponse("web/templates/index.html")

@app.get("/api/state")
async def get_state():
    return JSONResponse({
        "total_value_usd": 2500,
        "total_pnl": 80.5,
        "sol_price_usd": 150,
        "active_trades": [
            {
                "symbol": "SOL-USDC",
                "entry": 165.20,
                "qty": 1,
                "current_price": 142.10,
                "pnl": 115.5,
                "pnl_pct": 69.9,
                "direction": "SHORT",
                "leverage": 5.0,
                "sl": 178,
                "tp": 130,
                "agent_id": "main"
            },
            {
                "symbol": "WIF-USDC",
                "entry": 1.20,
                "qty": 100,
                "current_price": 1.55,
                "pnl": 35.0,
                "pnl_pct": 29.1,
                "direction": "LONG",
                "leverage": 1.0,
                "sl": 1.05,
                "tp": 1.90,
                "agent_id": "main"
            }
        ],
        "recent_trades": [],
        "leaderboard": [],
        "system": {"cpu":1,"ram":25,"disk":10,"uptime":"1h"}
    })

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5005)
