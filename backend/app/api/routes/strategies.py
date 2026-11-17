"""Strategy Lab & $100 Strategy Tester API Routes."""

from decimal import Decimal
import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
import pandas as pd
from sqlalchemy.orm import Session
from backend.app.core.clock_sync import now_utc, to_ist_str
from backend.app.core.symbol_utils import resolve_broker_symbol
from backend.app.db.models import StrategyScript, BacktestRun, TradingPairBot
from backend.app.db.session import get_db
from backend.app.strategy_lab.sandbox import validate_strategy_ast, validate_signal_geometry
from backend.app.strategy_lab.backtester import backtester, fetch_mt5_ohlcv

router = APIRouter(prefix="/strategies", tags=["Strategy Lab & Tester"])


# Pydantic Schemas
class StrategyValidateSchema(BaseModel):
    python_code: str = Field(..., description="Pasted Python strategy code")


class StrategyCreateSchema(BaseModel):
    name: str = Field(..., description="Strategy name")
    description: Optional[str] = None
    target_mode: str = Field("BOTH", description="SCALP, SWING, or BOTH")
    python_code: str = Field(..., description="Valid Python strategy code")
    default_params: Optional[Dict[str, Any]] = None


class StrategyUpdateSchema(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    target_mode: Optional[str] = None
    python_code: Optional[str] = None
    default_params: Optional[Dict[str, Any]] = None


class BacktestRequestSchema(BaseModel):
    strategy_id: Optional[int] = None
    strategy_code: Optional[str] = None
    symbol: str = "GOLD#"
    timeframe: str = "H1"
    test_mode: str = "ACCOUNT_100"  # ACCOUNT_100 or PER_TRADE_100
    bars_count: int = 500
    risk_pct: float = 1.0
    strategy_params: Optional[Dict[str, Any]] = None
    slippage_points: Optional[int] = None
    commission_per_lot: float = 0.0
    bars_data: Optional[List[Dict[str, Any]]] = None  # Uploaded or cached bar data


class AssignStrategySchema(BaseModel):
    scalp_strategy_id: Optional[int] = None
    swing_strategy_id: Optional[int] = None


@router.get("")
def list_strategies(db: Session = Depends(get_db)):
    """List all available strategies (built-in and custom, excluding deleted)."""
    strategies = (
        db.query(StrategyScript)
        .filter((StrategyScript.is_deleted == False) | (StrategyScript.is_deleted.is_(None)))
        .order_by(StrategyScript.is_builtin.desc(), StrategyScript.id.asc())
        .all()
    )
    res = []
    for s in strategies:
        params = json.loads(s.default_params_json) if s.default_params_json else {}
        res.append({
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "target_mode": s.target_mode,
            "python_code": s.python_code,
            "default_params": params,
            "is_builtin": s.is_builtin,
            "created_at_ist": to_ist_str(s.created_at_utc),
        })
    return res


@router.post("/validate")
def validate_code(payload: StrategyValidateSchema):
    """Dry-run AST security and syntax validation on pasted strategy code."""
    is_valid, msg, meta = validate_strategy_ast(payload.python_code)
    if not is_valid:
        return {"valid": False, "error": msg}
    return {
        "valid": True,
        "message": msg,
        "metadata": meta,
    }


@router.post("")
def create_strategy(payload: StrategyCreateSchema, db: Session = Depends(get_db)):
    """Save a new custom strategy script in MySQL."""
    is_valid, msg, _ = validate_strategy_ast(payload.python_code)
    if not is_valid:
        raise HTTPException(status_code=400, detail={"error": "AST_VALIDATION_FAILED", "message": msg})

    params_json = json.dumps(payload.default_params) if payload.default_params else None
    script = StrategyScript(
        name=payload.name,
        description=payload.description,
        target_mode=payload.target_mode.upper(),
        python_code=payload.python_code,
        default_params_json=params_json,
        is_builtin=False,
        created_at_utc=now_utc(),
    )
    db.add(script)
    db.commit()
    db.refresh(script)

    return {
        "status": "SUCCESS",
        "id": script.id,
        "name": script.name,
        "message": "Strategy saved successfully",
    }


@router.put("/{strategy_id}")
def update_strategy(strategy_id: int, payload: StrategyUpdateSchema, db: Session = Depends(get_db)):
    """Update a custom strategy (built-in strategies are protected)."""
    script = db.query(StrategyScript).filter_by(id=strategy_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Strategy not found")
    if script.is_builtin:
        raise HTTPException(status_code=403, detail="Built-in starter strategies cannot be modified.")

    if payload.python_code is not None:
        is_valid, msg, _ = validate_strategy_ast(payload.python_code)
        if not is_valid:
            raise HTTPException(status_code=400, detail={"error": "AST_VALIDATION_FAILED", "message": msg})
        script.python_code = payload.python_code

    if payload.name is not None:
        script.name = payload.name
    if payload.description is not None:
        script.description = payload.description
    if payload.target_mode is not None:
        script.target_mode = payload.target_mode.upper()
    if payload.default_params is not None:
        script.default_params_json = json.dumps(payload.default_params)

    db.commit()
    return {"status": "SUCCESS", "id": script.id, "message": "Strategy updated"}


@router.delete("/{strategy_id}")
def delete_strategy(strategy_id: int, db: Session = Depends(get_db)):
    """
    Delete any strategy (custom or built-in).
    Unassigns from TradingPairBot, unlinks BacktestRun, and marks is_deleted=True
    so startup boot will not revive it.
    """
    script = db.query(StrategyScript).filter_by(id=strategy_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Strategy not found")

    # 1. Unassign from any TradingPairBot
    db.query(TradingPairBot).filter(TradingPairBot.scalp_strategy_id == strategy_id).update(
        {TradingPairBot.scalp_strategy_id: None}
    )
    db.query(TradingPairBot).filter(TradingPairBot.swing_strategy_id == strategy_id).update(
        {TradingPairBot.swing_strategy_id: None}
    )

    # 2. Unlink from BacktestRun foreign keys to maintain referential integrity
    db.query(BacktestRun).filter(BacktestRun.strategy_id == strategy_id).update(
        {BacktestRun.strategy_id: None}
    )

    # 3. Soft-delete flag so built-ins or custom strategies are hidden and not auto-recreated
    script.is_deleted = True
    db.commit()
    return {"status": "SUCCESS", "message": f"Strategy #{strategy_id} ('{script.name}') deleted successfully."}


@router.post("/restore-defaults")
def restore_default_strategies(db: Session = Depends(get_db)):
    """Restore starter templates on demand."""
    from backend.app.strategy_lab.builtin_strategies import BUILTIN_STRATEGIES

    restored_count = 0
    for strat in BUILTIN_STRATEGIES:
        existing = db.query(StrategyScript).filter_by(name=strat["name"]).first()
        if existing:
            existing.is_deleted = False
            existing.python_code = strat["python_code"]
            existing.default_params_json = strat["default_params_json"]
            existing.description = strat["description"]
            existing.target_mode = strat["target_mode"]
            existing.is_builtin = True
            restored_count += 1
        else:
            new_strat = StrategyScript(
                name=strat["name"],
                description=strat["description"],
                target_mode=strat["target_mode"],
                python_code=strat["python_code"],
                default_params_json=strat["default_params_json"],
                is_builtin=True,
                is_deleted=False,
                created_at_utc=now_utc(),
            )
            db.add(new_strat)
            restored_count += 1

    db.commit()
    return {"status": "SUCCESS", "restored_count": restored_count, "message": f"Restored {restored_count} starter strategy templates."}


@router.delete("/backtests/{run_id}")
def delete_backtest_run(run_id: int, db: Session = Depends(get_db)):
    """Delete an individual backtest run from historical records."""
    run = db.query(BacktestRun).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    db.delete(run)
    db.commit()
    return {"status": "SUCCESS", "message": f"Backtest run #{run_id} deleted"}


@router.post("/backtest")
async def execute_backtest(payload: BacktestRequestSchema, db: Session = Depends(get_db)):
    """Execute a realistic $100 backtest, save BacktestRun, and return full metrics."""
    code_to_run = payload.strategy_code
    strat_id = payload.strategy_id

    if strat_id and not code_to_run:
        script = db.query(StrategyScript).filter_by(id=strat_id).first()
        if not script:
            raise HTTPException(status_code=404, detail="StrategyScript not found")
        code_to_run = script.python_code

    if not code_to_run:
        raise HTTPException(status_code=400, detail="Must provide strategy_code or a valid strategy_id.")

    # Validate code AST
    is_valid, msg, _ = validate_strategy_ast(code_to_run)
    if not is_valid:
        raise HTTPException(status_code=400, detail={"error": "AST_SECURITY_VIOLATION", "message": msg})

    # Resolve canonical symbol
    resolved_symbol = resolve_broker_symbol(payload.symbol, db)

    # Prepare OHLCV DataFrame
    if payload.bars_data:
        df = pd.DataFrame(payload.bars_data)
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], utc=True)
    else:
        df = await fetch_mt5_ohlcv(resolved_symbol, payload.timeframe, payload.bars_count)
        if df is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "MT5_DATA_UNAVAILABLE",
                    "message": f"Could not fetch live bars for '{resolved_symbol}'. MT5 terminal may be disconnected and no bars_data was provided.",
                },
            )

    try:
        results = backtester.run_backtest(
            strategy_code=code_to_run,
            symbol=resolved_symbol,
            df=df,
            timeframe=payload.timeframe,
            test_mode=payload.test_mode,
            strategy_params=payload.strategy_params,
            strategy_id=strat_id,
            risk_pct=payload.risk_pct,
            slippage_points=payload.slippage_points,
            commission_per_lot=payload.commission_per_lot,
            save_to_db=True,
        )
        return results
    except Exception as e:
        logger.error(f"Backtest execution failed: {e}")
        raise HTTPException(status_code=500, detail=f"Backtest error: {str(e)}")


@router.get("/backtests")
def list_backtests(
    symbol: Optional[str] = None,
    strategy_id: Optional[int] = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    """List historical backtest runs."""
    query = db.query(BacktestRun)
    if symbol:
        resolved = resolve_broker_symbol(symbol, db)
        clean = resolved.rstrip("#")
        query = query.filter((BacktestRun.symbol == resolved) | (BacktestRun.symbol == clean) | (BacktestRun.symbol == f"{clean}#"))
    if strategy_id:
        query = query.filter(BacktestRun.strategy_id == strategy_id)

    runs = query.order_by(BacktestRun.created_at_utc.desc()).limit(limit).all()
    res = []
    for r in runs:
        res.append({
            "id": r.id,
            "strategy_id": r.strategy_id,
            "symbol": r.symbol,
            "timeframe": r.timeframe,
            "test_mode": r.test_mode,
            "capital_usd": float(r.capital_usd),
            "total_trades": r.total_trades,
            "win_rate_pct": float(r.win_rate_pct),
            "gross_pnl_usd": float(r.gross_pnl_usd),
            "spread_cost_usd": float(r.spread_cost_usd),
            "swap_cost_usd": float(r.swap_cost_usd),
            "commission_cost_usd": float(r.commission_cost_usd),
            "net_pnl_usd": float(r.net_pnl_usd),
            "net_roi_pct": float(r.net_roi_pct),
            "max_dd_pct": float(r.max_dd_pct),
            "created_at_ist": to_ist_str(r.created_at_utc),
        })
    return res


# Pair Strategy Assignment Route (can also be called via /api/pairs/{symbol}/assign-strategy)
@router.post("/assign-pair/{symbol}")
def assign_strategy_to_pair(symbol: str, payload: AssignStrategySchema, db: Session = Depends(get_db)):
    """Assign scalp_strategy_id and/or swing_strategy_id to a TradingPairBot in MySQL."""
    sym = symbol.upper()
    pair = db.query(TradingPairBot).filter(
        (TradingPairBot.symbol == sym) | (TradingPairBot.symbol == f"{sym}#")
    ).first()
    if not pair:
        raise HTTPException(status_code=404, detail=f"TradingPairBot '{symbol}' not found")

    if payload.scalp_strategy_id is not None:
        if payload.scalp_strategy_id > 0:
            strat = db.query(StrategyScript).filter_by(id=payload.scalp_strategy_id).first()
            if not strat:
                raise HTTPException(status_code=404, detail=f"Strategy #{payload.scalp_strategy_id} not found")
            pair.scalp_strategy_id = payload.scalp_strategy_id
        else:
            pair.scalp_strategy_id = None

    if payload.swing_strategy_id is not None:
        if payload.swing_strategy_id > 0:
            strat = db.query(StrategyScript).filter_by(id=payload.swing_strategy_id).first()
            if not strat:
                raise HTTPException(status_code=404, detail=f"Strategy #{payload.swing_strategy_id} not found")
            pair.swing_strategy_id = payload.swing_strategy_id
        else:
            pair.swing_strategy_id = None

    db.commit()
    return {
        "status": "SUCCESS",
        "symbol": pair.symbol,
        "scalp_strategy_id": pair.scalp_strategy_id,
        "swing_strategy_id": pair.swing_strategy_id,
        "message": f"Strategies assigned to {pair.symbol} successfully.",
    }


class SaveSnapshotSchema(BaseModel):
    backtest_run_id: Optional[int] = None
    strategy_id: Optional[int] = None
    custom_label: str = Field(..., description="Custom label for strategy vault bookmark")
    symbol: str = "GOLD#"
    timeframe: str = "H1"
    test_mode: str = "ACCOUNT_100"
    strategy_code: str = Field(..., description="Snapshot of the strategy Python code")
    params: Optional[Dict[str, Any]] = None
    metrics: Dict[str, Any] = Field(..., description="PnL and KPI metrics dictionary")


@router.post("/save-snapshot")
def save_strategy_snapshot(payload: SaveSnapshotSchema, db: Session = Depends(get_db)):
    """Save/bookmark strategy with its tested backtest PnL metrics to MySQL vault."""
    m = payload.metrics
    record = None
    if payload.backtest_run_id:
        record = db.query(BacktestRun).filter_by(id=payload.backtest_run_id).first()

    if not record:
        record = BacktestRun(
            strategy_id=payload.strategy_id,
            symbol=resolve_broker_symbol(payload.symbol, db),
            timeframe=payload.timeframe,
            test_mode=payload.test_mode,
            capital_usd=Decimal(str(m.get("capital_usd", 100.0))),
            total_trades=int(m.get("total_trades", 0)),
            win_rate_pct=Decimal(str(m.get("win_rate_pct", 0.0))),
            gross_pnl_usd=Decimal(str(m.get("gross_pnl_usd", 0.0))),
            spread_cost_usd=Decimal(str(m.get("spread_cost_usd", 0.0))),
            swap_cost_usd=Decimal(str(m.get("swap_cost_usd", 0.0))),
            commission_cost_usd=Decimal(str(m.get("commission_cost_usd", 0.0))),
            net_pnl_usd=Decimal(str(m.get("net_pnl_usd", 0.0))),
            net_roi_pct=Decimal(str(m.get("net_roi_pct", 0.0))),
            max_dd_pct=Decimal(str(m.get("max_dd_pct", 0.0))),
            profit_factor=Decimal(str(m.get("profit_factor", 0.0))),
            trades_json=json.dumps(m.get("trades", [])),
            created_at_utc=now_utc(),
        )
        db.add(record)

    record.is_saved_bookmark = True
    record.custom_label = payload.custom_label
    record.strategy_code_snapshot = payload.strategy_code
    record.params_json = json.dumps(payload.params or {})
    if "profit_factor" in m:
        record.profit_factor = Decimal(str(m["profit_factor"]))

    db.commit()
    db.refresh(record)
    return {
        "status": "SUCCESS",
        "id": record.id,
        "custom_label": record.custom_label,
        "message": f"Strategy snapshot '{record.custom_label}' saved to PnL Vault.",
    }


@router.get("/saved-vault")
def list_saved_vault(db: Session = Depends(get_db)):
    """List all saved strategies and backtest PnL snapshots from MySQL vault."""
    saved = db.query(BacktestRun).filter_by(is_saved_bookmark=True).order_by(BacktestRun.net_pnl_usd.desc()).all()
    res = []
    for r in saved:
        res.append({
            "id": r.id,
            "strategy_id": r.strategy_id,
            "custom_label": r.custom_label or f"Strategy Run #{r.id}",
            "symbol": r.symbol,
            "timeframe": r.timeframe,
            "test_mode": r.test_mode,
            "capital_usd": float(r.capital_usd),
            "total_trades": r.total_trades,
            "win_rate_pct": float(r.win_rate_pct),
            "net_pnl_usd": float(r.net_pnl_usd),
            "net_roi_pct": float(r.net_roi_pct),
            "profit_factor": float(r.profit_factor),
            "max_dd_pct": float(r.max_dd_pct),
            "spread_cost_usd": float(r.spread_cost_usd),
            "swap_cost_usd": float(r.swap_cost_usd),
            "strategy_code_snapshot": r.strategy_code_snapshot,
            "params_json": r.params_json,
            "created_at_ist": to_ist_str(r.created_at_utc),
        })
    return res


@router.delete("/saved-vault/{run_id}")
def delete_saved_vault_item(run_id: int, db: Session = Depends(get_db)):
    """Delete a saved strategy snapshot from the vault."""
    item = db.query(BacktestRun).filter_by(id=run_id, is_saved_bookmark=True).first()
    if not item:
        raise HTTPException(status_code=404, detail="Saved vault snapshot not found")
    item.is_saved_bookmark = False
    db.commit()
    return {"status": "SUCCESS", "message": f"Snapshot #{run_id} removed from vault"}


