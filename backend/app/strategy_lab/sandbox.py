"""AST-Guarded Python Strategy Sandbox & Validation Engine.

Parses user-pasted strategy code via Python AST, rejects dangerous constructs,
injects pre-vetted indicator helpers into execution globals, enforces a 2-second
timeout, and validates signal geometry.
"""

import ast
import concurrent.futures
import logging
from typing import Any, Callable, Dict, Optional, Tuple
import numpy as np
import pandas as pd
from backend.app.strategy_lab.indicators import (
    atr,
    ema,
    rsi,
    swing_highs,
    swing_lows,
    detect_fvg,
    detect_liquidity_sweep,
)

logger = logging.getLogger(__name__)

BLOCKED_CALLS = {
    "open",
    "exec",
    "eval",
    "compile",
    "__import__",
    "getattr",
    "setattr",
    "delattr",
    "globals",
    "locals",
    "vars",
    "breakpoint",
    "input",
    "exit",
    "quit",
    "help",
    "memoryview",
}

SAFE_BUILTINS = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "len": len,
    "range": range,
    "enumerate": enumerate,
    "zip": zip,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "dict": dict,
    "list": list,
    "tuple": tuple,
    "set": set,
    "sum": sum,
    "isinstance": isinstance,
    "print": print,
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "True": True,
    "False": False,
    "None": None,
}


class SecurityViolationError(Exception):
    """Raised when pasted strategy code violates sandbox security constraints."""
    pass


class ASTSecurityVisitor(ast.NodeVisitor):
    """Inspects Python AST nodes to block dangerous execution vectors."""

    def visit_Import(self, node: ast.Import):
        raise SecurityViolationError(
            f"Line {node.lineno}: 'import' statements are strictly forbidden. "
            f"Pre-vetted helpers (pd, np, atr, ema, rsi, etc.) are automatically injected."
        )

    def visit_ImportFrom(self, node: ast.ImportFrom):
        raise SecurityViolationError(
            f"Line {node.lineno}: 'from ... import ...' statements are strictly forbidden."
        )

    def visit_Attribute(self, node: ast.Attribute):
        if node.attr.startswith("__"):
            raise SecurityViolationError(
                f"Line {node.lineno}: Accessing dunder attributes ('{node.attr}') is strictly forbidden."
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name):
            if node.func.id in BLOCKED_CALLS:
                raise SecurityViolationError(
                    f"Line {node.lineno}: Calling blocked built-in function '{node.func.id}()' is strictly forbidden."
                )
        self.generic_visit(node)


def validate_strategy_ast(code_str: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Parse and validate user-pasted strategy code syntax and security rules.
    Returns: (is_valid, message, extracted_metadata)
    """
    if not code_str or not code_str.strip():
        return False, "Strategy code cannot be empty.", None

    try:
        tree = ast.parse(code_str, filename="<strategy_check>")
    except SyntaxError as e:
        return False, f"Syntax Error at line {e.lineno}: {e.msg}", None

    # Enforce security AST inspection
    visitor = ASTSecurityVisitor()
    try:
        visitor.visit(tree)
    except SecurityViolationError as e:
        return False, str(e), None

    # Verify standard contract functions
    has_evaluate = False
    has_default_params = False

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "evaluate":
            # Must accept df and params
            arg_names = [a.arg for a in node.args.args]
            if len(arg_names) >= 2 and arg_names[0] == "df" and arg_names[1] == "params":
                has_evaluate = True
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "DEFAULT_PARAMS":
                    has_default_params = True

    if not has_evaluate:
        return (
            False,
            "Strategy contract violation: Must define 'def evaluate(df: pd.DataFrame, params: dict) -> dict | None:'",
            None,
        )

    return True, "AST Security and Contract validation PASSED.", {"has_default_params": has_default_params}


def validate_signal_geometry(signal: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """
    Validate standard signal geometry:
    BUY:  sl < entry < tp1 <= tp2
    SELL: sl > entry > tp1 >= tp2
    """
    if signal is None:
        return True, "OK"

    if not isinstance(signal, dict):
        return False, "Signal must be a dictionary or None."

    required = ["signal", "mode", "entry", "sl", "tp1", "tp2"]
    for k in required:
        if k not in signal:
            return False, f"Signal missing required key: '{k}'"

    sig_type = str(signal["signal"]).upper()
    mode = str(signal["mode"]).upper()

    if sig_type not in ("BUY", "SELL"):
        return False, f"Invalid signal type '{sig_type}'. Must be 'BUY' or 'SELL'."

    if mode not in ("SCALP", "SWING"):
        return False, f"Invalid mode '{mode}'. Must be 'SCALP' or 'SWING'."

    try:
        entry = float(signal["entry"])
        sl = float(signal["sl"])
        tp1 = float(signal["tp1"])
        tp2 = float(signal["tp2"])
    except (ValueError, TypeError) as e:
        return False, f"Signal prices must be valid numeric values: {e}"

    if entry <= 0 or sl <= 0 or tp1 <= 0 or tp2 <= 0:
        return False, "Prices must be positive numbers strictly greater than 0."

    if sig_type == "BUY":
        if not (sl < entry < tp1 <= tp2):
            return False, f"Invalid BUY geometry: sl ({sl}) < entry ({entry}) < tp1 ({tp1}) <= tp2 ({tp2}) violated."
    elif sig_type == "SELL":
        if not (sl > entry > tp1 >= tp2):
            return False, f"Invalid SELL geometry: sl ({sl}) > entry ({entry}) > tp1 ({tp1}) >= tp2 ({tp2}) violated."

    return True, "OK"


class StrategySandbox:
    """Executes validated strategy code within a secure, injected runtime."""

    def __init__(self, code_str: str):
        is_ok, msg, _ = validate_strategy_ast(code_str)
        if not is_ok:
            raise SecurityViolationError(msg)

        self.code_str = code_str
        self._compiled_code = compile(code_str, filename="<strategy_sandbox>", mode="exec")
        self._env = self._build_execution_environment()

        # Execute code to bind DEFAULT_PARAMS and evaluate function
        exec(self._compiled_code, self._env)

        self.default_params: Dict[str, Any] = self._env.get("DEFAULT_PARAMS", {})
        self._evaluate_fn: Callable = self._env.get("evaluate")
        if not callable(self._evaluate_fn):
            raise ValueError("Strategy does not define a callable 'evaluate' function.")

    def _build_execution_environment(self) -> Dict[str, Any]:
        """Construct isolated namespace with pre-vetted indicator helpers."""
        env: Dict[str, Any] = {
            "__builtins__": SAFE_BUILTINS.copy(),
            "pd": pd,
            "np": np,
            "atr": atr,
            "ema": ema,
            "rsi": rsi,
            "swing_highs": swing_highs,
            "swing_lows": swing_lows,
            "detect_fvg": detect_fvg,
            "detect_liquidity_sweep": detect_liquidity_sweep,
        }
        return env

    def evaluate(
        self,
        df: pd.DataFrame,
        params: Optional[Dict[str, Any]] = None,
        timeout_sec: float = 2.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluate strategy with timeout protection and signal geometry validation.
        """
        merged_params = dict(self.default_params)
        if params:
            merged_params.update(params)

        def _run():
            return self._evaluate_fn(df, merged_params)

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_run)
                signal = future.result(timeout=timeout_sec)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"Strategy evaluation exceeded execution limit of {timeout_sec}s.")
        except Exception as e:
            logger.error(f"Error during strategy evaluate() call: {e}")
            raise

        if signal is not None:
            is_valid, geom_msg = validate_signal_geometry(signal)
            if not is_valid:
                logger.warning(f"Strategy returned invalid signal geometry: {geom_msg}")
                return None

        return signal

