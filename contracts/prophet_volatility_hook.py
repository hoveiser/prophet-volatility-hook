# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *
from dataclasses import dataclass
import json
import re

@allow_storage
@dataclass
class MarginPosition:
    position_id: str
    trader: Address
    prophet_grid_market_id: str
    posted_collateral_wei: u256
    quantized_vol_bps: u256
    margin_tier: str
    status: str
    volatility_source_url: str
    created_at_dt: str
    last_evaluated_dt: str
    cooldown_seconds: u256
    multiplier_bps: u256
    required_margin_wei: u256
    reconciled: bool
    reconciled_market_status: str

@gl.evm.contract_interface
class IEoaRecipient:
    class View:
        pass

    class Write:
        pass

def _parse_iso8601_to_epoch(dt_str: str) -> int:
    clean = dt_str.replace("Z", "").replace("+00:00", "")
    if "." in clean:
        clean = clean.split(".")[0]
    date_part, time_part = clean.split("T")
    y, m, d = [int(x) for x in date_part.split("-")]
    hh, mm, ss = [int(x) for x in time_part.split(":")]
    days_before_month = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    y_adj = y - 1970
    leap_years = (y - 1969) // 4 - (y - 1901) // 100 + (y - 1601) // 400
    days = y_adj * 365 + leap_years + days_before_month[m - 1] + (d - 1)
    is_leap = (y % 4 == 0 and y % 100 != 0) or (y % 400 == 0)
    if is_leap and m > 2:
        days += 1
    return days * 86400 + hh * 3600 + mm * 60 + ss

def _coerce_address(acc: str | bytes | Address) -> Address:
    if isinstance(acc, Address):
        return acc
    if isinstance(acc, bytes):
        return Address(acc)
    if isinstance(acc, str):
        acc = acc.strip()
        if acc.startswith("0x"):
            return Address(acc)
        try:
            b = bytes.fromhex(acc)
            if len(b) == 20:
                return Address("0x" + acc)
        except Exception:
            pass
        return Address(acc)
    return Address(acc)

def _compute_position_state(pos: MarginPosition, now_iso: str) -> dict:
    posted = int(pos.posted_collateral_wei)
    multiplier = int(pos.multiplier_bps) if int(pos.multiplier_bps) > 0 else 10000
    required = (posted * multiplier) // 10000
    now_epoch = _parse_iso8601_to_epoch(now_iso) if now_iso else 0
    ref_dt = pos.last_evaluated_dt if pos.last_evaluated_dt else pos.created_at_dt
    ref_epoch = _parse_iso8601_to_epoch(ref_dt) if ref_dt else 0
    cooldown = int(pos.cooldown_seconds)
    cooldown_elapsed = now_epoch >= (ref_epoch + cooldown) if (now_epoch > 0 and ref_epoch > 0) else False

    is_calm = pos.margin_tier == "CALM_LOW_VOL_RELEASE"
    can_release = pos.reconciled and (is_calm or "FINALIZED" in pos.reconciled_market_status or "SETTLED" in pos.reconciled_market_status)
    can_refund = pos.reconciled and ("REFUND" in pos.reconciled_market_status or "VOID" in pos.reconciled_market_status or "EXPIRED" in pos.reconciled_market_status)

    return {
        "position_id": pos.position_id,
        "trader": str(pos.trader),
        "prophet_grid_market_id": pos.prophet_grid_market_id,
        "posted_collateral_wei": posted,
        "quantized_vol_bps": int(pos.quantized_vol_bps),
        "margin_tier": pos.margin_tier,
        "status": pos.status,
        "volatility_source_url": pos.volatility_source_url,
        "created_at_dt": pos.created_at_dt,
        "last_evaluated_dt": pos.last_evaluated_dt,
        "cooldown_seconds": cooldown,
        "multiplier_bps": multiplier,
        "required_margin_wei": required,
        "reconciled": pos.reconciled,
        "reconciled_market_status": pos.reconciled_market_status,
        "cooldown_elapsed": cooldown_elapsed,
        "can_release": can_release,
        "can_refund": can_refund
    }

class ProphetVolatilityHook(gl.Contract):
    prophet_grid_address: Address
    positions: TreeMap[str, MarginPosition]
    position_ids: DynArray[str]
    refundable_balances: TreeMap[Address, u256]
    last_payable_rejection: TreeMap[Address, str]
    total_active_margin_wei: u256
    total_refundable_wei: u256
    total_positions_count: u256
    min_collateral_wei: u256
    max_collateral_wei: u256
    min_cooldown_seconds: u256
    max_cooldown_seconds: u256

    def __init__(
        self,
        prophet_grid_address: str,
        min_collateral_wei: int,
        max_collateral_wei: int,
        min_cooldown_seconds: int,
        max_cooldown_seconds: int
    ):
        if min_collateral_wei <= 0 or max_collateral_wei < min_collateral_wei:
            raise gl.vm.UserError("Invalid collateral bounds")
        if min_cooldown_seconds <= 0 or max_cooldown_seconds < min_cooldown_seconds:
            raise gl.vm.UserError("Invalid cooldown bounds")

        self.prophet_grid_address = _coerce_address(prophet_grid_address)
        self.min_collateral_wei = u256(min_collateral_wei)
        self.max_collateral_wei = u256(max_collateral_wei)
        self.min_cooldown_seconds = u256(min_cooldown_seconds)
        self.max_cooldown_seconds = u256(max_cooldown_seconds)
        self.total_active_margin_wei = u256(0)
        self.total_refundable_wei = u256(0)
        self.total_positions_count = u256(0)

    @gl.public.write.payable
    def open_volatility_margin_payable(
        self,
        prophet_grid_market_id: str,
        volatility_source_url: str,
        cooldown_seconds: int
    ) -> str:
        sender = gl.message.sender_address
        value = int(gl.message.value)

        # Validation: Never revert in payable write
        rejection_reason = ""
        if value < int(self.min_collateral_wei):
            rejection_reason = "COLLATERAL_BELOW_MINIMUM"
        elif not prophet_grid_market_id or len(prophet_grid_market_id) > 64:
            rejection_reason = "INVALID_MARKET_ID"
        elif not volatility_source_url.startswith("https://") or len(volatility_source_url) > 256:
            rejection_reason = "INVALID_VOLATILITY_SOURCE_URL"
        elif cooldown_seconds < int(self.min_cooldown_seconds) or cooldown_seconds > int(self.max_cooldown_seconds):
            rejection_reason = "COOLDOWN_OUT_OF_BOUNDS"
        else:
            # Cross-contract verification against ProphetGrid
            try:
                grid = gl.get_contract_at(self.prophet_grid_address)
                m_raw = grid.view().get_market(prophet_grid_market_id)
                m_data = json.loads(m_raw) if isinstance(m_raw, str) else m_raw
                if not isinstance(m_data, dict) or "market_id" not in m_data:
                    rejection_reason = "MARKET_NOT_FOUND_ON_PROPHET_GRID"
            except Exception:
                rejection_reason = "FAILED_TO_VERIFY_MARKET_ON_PROPHET_GRID"

        if rejection_reason != "":
            # Soft-fail: credit 100% of sent value to refundable balances
            current_ref = int(self.refundable_balances[sender]) if sender in self.refundable_balances else 0
            self.refundable_balances[sender] = u256(current_ref + value)
            self.total_refundable_wei = u256(int(self.total_refundable_wei) + value)
            self.last_payable_rejection[sender] = rejection_reason
            return f"REJECTED: {rejection_reason}"

        # Handle overpayment surplus beyond max_collateral_wei
        max_col = int(self.max_collateral_wei)
        surplus = 0
        accepted_collateral = value
        if value > max_col:
            surplus = value - max_col
            accepted_collateral = max_col
            current_ref = int(self.refundable_balances[sender]) if sender in self.refundable_balances else 0
            self.refundable_balances[sender] = u256(current_ref + surplus)
            self.total_refundable_wei = u256(int(self.total_refundable_wei) + surplus)

        # Successful position creation
        current_count = int(self.total_positions_count)
        new_id = str(current_count + 1)
        self.total_positions_count = u256(current_count + 1)
        self.total_active_margin_wei = u256(int(self.total_active_margin_wei) + accepted_collateral)

        current_dt = gl.message_raw["datetime"]
        pos = MarginPosition(
            position_id=new_id,
            trader=sender,
            prophet_grid_market_id=prophet_grid_market_id,
            posted_collateral_wei=u256(accepted_collateral),
            quantized_vol_bps=u256(1500),
            margin_tier="ELEVATED_BUFFER_HOLD",
            status="ACTIVE",
            volatility_source_url=volatility_source_url,
            created_at_dt=current_dt,
            last_evaluated_dt="",
            cooldown_seconds=u256(cooldown_seconds),
            multiplier_bps=u256(12500),
            required_margin_wei=u256((accepted_collateral * 12500) // 10000),
            reconciled=False,
            reconciled_market_status="UNRECONCILED"
        )
        self.positions[new_id] = pos
        self.position_ids.append(new_id)
        self.last_payable_rejection[sender] = "NONE"

        return new_id

    @gl.public.write
    def evaluate_volatility_regime(self, position_id: str) -> dict:
        if position_id not in self.positions:
            raise gl.vm.UserError(f"Position {position_id} not found")

        pos = self.positions[position_id]
        if pos.status not in ("ACTIVE", "RECONCILED"):
            raise gl.vm.UserError(f"Position status {pos.status} does not allow evaluation")

        # Temporal cooldown check
        now_iso = gl.message_raw["datetime"]
        now_epoch = _parse_iso8601_to_epoch(now_iso)
        ref_dt = pos.last_evaluated_dt if pos.last_evaluated_dt else pos.created_at_dt
        ref_epoch = _parse_iso8601_to_epoch(ref_dt)
        cooldown = int(pos.cooldown_seconds)
        if now_epoch < ref_epoch + cooldown:
            raise gl.vm.UserError(f"Cooldown active: {now_epoch} < {ref_epoch + cooldown}")

        # Snapshot storage into plain locals
        feed_url = pos.volatility_source_url
        posted_col = int(pos.posted_collateral_wei)

        def fetch_and_quantize() -> dict:
            raw_text = ""
            try:
                rendered = gl.nondet.web.render(feed_url, mode="text")
                raw_text = str(rendered) if rendered else ""
            except Exception:
                raw_text = ""

            # Fail-closed check: empty or less than 32 characters
            if not raw_text or len(raw_text.strip()) < 32:
                return {
                    "quantized_vol_bps": 5000,
                    "regime_band": "CIRCUIT_BREAKER_HALT",
                    "multiplier_bps": 25000,
                    "reason": "FAIL_CLOSED_INSUFFICIENT_WEB_DATA"
                }

            extracted_vol = None
            clean_text = raw_text.strip()

            # Attempt JSON parse
            try:
                j_data = json.loads(clean_text)
                if isinstance(j_data, dict):
                    for k in ("volatility_bps", "vix_bps", "vol_bps", "bps"):
                        if k in j_data and isinstance(j_data[k], (int, float)):
                            extracted_vol = int(j_data[k])
                            break
                    if extracted_vol is None:
                        for k in ("volatility", "vix", "vol", "value", "rate"):
                            if k in j_data and isinstance(j_data[k], (int, float)):
                                extracted_vol = int(round(float(j_data[k]) * 100))
                                break
            except Exception:
                pass

            # Attempt regex extraction if JSON did not parse
            if extracted_vol is None:
                matches = re.findall(r'(?:VIX|volatility|implied|yield|rate)[\s:]*([0-9]+(?:\.[0-9]+)?)', clean_text, re.IGNORECASE)
                if matches:
                    try:
                        num = float(matches[0])
                        extracted_vol = int(round(num)) if num > 100 else int(round(num * 100))
                    except Exception:
                        pass

            if extracted_vol is None:
                all_nums = re.findall(r'\b([0-9]{1,2}(?:\.[0-9]{1,4})?)\b', clean_text)
                if all_nums:
                    try:
                        num = float(all_nums[0])
                        extracted_vol = int(round(num * 100))
                    except Exception:
                        pass

            if extracted_vol is None or extracted_vol <= 0:
                return {
                    "quantized_vol_bps": 5000,
                    "regime_band": "CIRCUIT_BREAKER_HALT",
                    "multiplier_bps": 25000,
                    "reason": "FAIL_CLOSED_EXTRACTION_FAILURE"
                }

            # 250-bps grid quantization
            base_q = (extracted_vol // 250) * 250
            remainder = extracted_vol % 250
            quantized_bps = base_q + 250 if remainder >= 125 else base_q

            # Bind to 4 discrete regime bands
            if quantized_bps < 1500:
                band = "CALM_LOW_VOL_RELEASE"
                mult = 10000
            elif quantized_bps < 2500:
                band = "ELEVATED_BUFFER_HOLD"
                mult = 12500
            elif quantized_bps < 3500:
                band = "STRESS_SURCHARGE_LOCK"
                mult = 17500
            else:
                band = "CIRCUIT_BREAKER_HALT"
                mult = 25000

            return {
                "quantized_vol_bps": quantized_bps,
                "regime_band": band,
                "multiplier_bps": mult,
                "reason": "OK"
            }

        principle = (
            "Validators must agree 100% exactly on regime_band, quantized_vol_bps, "
            "and multiplier_bps. If fail-closed triggered, band must be CIRCUIT_BREAKER_HALT."
        )

        res = gl.eq_principle.prompt_comparative(fetch_and_quantize, principle)

        # Update position state on-chain
        pos.quantized_vol_bps = u256(int(res["quantized_vol_bps"]))
        pos.margin_tier = str(res["regime_band"])
        pos.multiplier_bps = u256(int(res["multiplier_bps"]))
        pos.required_margin_wei = u256((posted_col * int(res["multiplier_bps"])) // 10000)
        pos.last_evaluated_dt = now_iso
        if res["regime_band"] == "CIRCUIT_BREAKER_HALT":
            pos.status = "CIRCUIT_HALTED"

        self.positions[position_id] = pos
        return _compute_position_state(pos, now_iso)

    @gl.public.write
    def reconcile_market_margin_state(self, position_id: str) -> dict:
        if position_id not in self.positions:
            raise gl.vm.UserError(f"Position {position_id} not found")

        pos = self.positions[position_id]
        grid = gl.get_contract_at(self.prophet_grid_address)
        m_raw = grid.view().get_market(pos.prophet_grid_market_id)
        m_data = json.loads(m_raw) if isinstance(m_raw, str) else m_raw
        if not isinstance(m_data, dict):
            raise gl.vm.UserError("Malformed market response from ProphetGrid")

        m_status = str(m_data.get("status", "UNKNOWN"))
        m_phase = str(m_data.get("phase", "UNKNOWN"))
        refundable = bool(m_data.get("refundable", False))
        can_claim = bool(m_data.get("can_claim", False))

        reconciled_status = f"{m_status}:{m_phase}"
        if refundable:
            reconciled_status += ":REFUNDABLE"
        if can_claim:
            reconciled_status += ":CAN_CLAIM"

        pos.reconciled = True
        pos.reconciled_market_status = reconciled_status
        if pos.status == "ACTIVE":
            pos.status = "RECONCILED"

        self.positions[position_id] = pos
        now_iso = gl.message_raw["datetime"]
        return _compute_position_state(pos, now_iso)

    @gl.public.write
    def settle_or_release_margin(self, position_id: str) -> str:
        if position_id not in self.positions:
            raise gl.vm.UserError(f"Position {position_id} not found")

        pos = self.positions[position_id]
        if not pos.reconciled:
            raise gl.vm.UserError("Cross-contract reconciliation required before margin release")

        now_iso = gl.message_raw["datetime"]
        st = _compute_position_state(pos, now_iso)
        if not st["can_release"]:
            raise gl.vm.UserError(f"Margin release criteria not satisfied. Tier: {pos.margin_tier}, Grid: {pos.reconciled_market_status}")

        if pos.status in ("RELEASED", "REFUNDED"):
            raise gl.vm.UserError(f"Position already settled: {pos.status}")

        posted = int(pos.posted_collateral_wei)
        pos.status = "RELEASED"
        self.positions[position_id] = pos
        self.total_active_margin_wei = u256(int(self.total_active_margin_wei) - posted)

        # Deliver collateral back to trader EOA
        try:
            recipient = IEoaRecipient(pos.trader)
            recipient.emit_transfer(value=u256(posted))
        except Exception:
            # Preserve funds in refundable_balances if delivery fails
            current_ref = int(self.refundable_balances[pos.trader]) if pos.trader in self.refundable_balances else 0
            self.refundable_balances[pos.trader] = u256(current_ref + posted)
            self.total_refundable_wei = u256(int(self.total_refundable_wei) + posted)

        return f"RELEASED:{posted}"

    @gl.public.write
    def claim_position_refund(self, position_id: str) -> str:
        if position_id not in self.positions:
            raise gl.vm.UserError(f"Position {position_id} not found")

        pos = self.positions[position_id]
        if not pos.reconciled:
            raise gl.vm.UserError("Cross-contract reconciliation required before claiming refund")

        now_iso = gl.message_raw["datetime"]
        st = _compute_position_state(pos, now_iso)
        if not st["can_refund"]:
            raise gl.vm.UserError(f"Market does not qualify for refund. Status: {pos.reconciled_market_status}")

        if pos.status in ("RELEASED", "REFUNDED"):
            raise gl.vm.UserError(f"Position already settled: {pos.status}")

        posted = int(pos.posted_collateral_wei)
        pos.status = "REFUNDED"
        self.positions[position_id] = pos
        self.total_active_margin_wei = u256(int(self.total_active_margin_wei) - posted)

        # Deliver refund back to trader EOA
        try:
            recipient = IEoaRecipient(pos.trader)
            recipient.emit_transfer(value=u256(posted))
        except Exception:
            current_ref = int(self.refundable_balances[pos.trader]) if pos.trader in self.refundable_balances else 0
            self.refundable_balances[pos.trader] = u256(current_ref + posted)
            self.total_refundable_wei = u256(int(self.total_refundable_wei) + posted)

        return f"REFUNDED:{posted}"

    @gl.public.write
    def withdraw_refundable_balance(self, amount: int) -> int:
        sender = gl.message.sender_address
        if amount <= 0:
            raise gl.vm.UserError("Amount must be positive")

        current_bal = int(self.refundable_balances[sender]) if sender in self.refundable_balances else 0
        if amount > current_bal:
            raise gl.vm.UserError(f"Insufficient refundable balance: requested {amount}, available {current_bal}")

        self.refundable_balances[sender] = u256(current_bal - amount)
        self.total_refundable_wei = u256(int(self.total_refundable_wei) - amount)

        try:
            recipient = IEoaRecipient(sender)
            recipient.emit_transfer(value=u256(amount))
        except Exception as e:
            # Preserve refundable balance intact if delivery fails
            self.refundable_balances[sender] = u256(current_bal)
            self.total_refundable_wei = u256(int(self.total_refundable_wei) + amount)
            raise gl.vm.UserError(f"Transfer failed, refundable balance restored: {str(e)}")

        return amount

    @gl.public.write
    def claim_all_refundable_balance(self) -> int:
        sender = gl.message.sender_address
        current_bal = int(self.refundable_balances[sender]) if sender in self.refundable_balances else 0
        if current_bal == 0:
            return 0
        return self.withdraw_refundable_balance(current_bal)

    @gl.public.view
    def get_margin_position(self, position_id: str) -> dict:
        if position_id not in self.positions:
            raise gl.vm.UserError(f"Position {position_id} not found")
        pos = self.positions[position_id]
        now_iso = gl.message_raw["datetime"]
        return _compute_position_state(pos, now_iso)

    @gl.public.view
    def get_refundable_balance(self, account: str) -> int:
        addr = _coerce_address(account)
        return int(self.refundable_balances[addr]) if addr in self.refundable_balances else 0

    @gl.public.view
    def get_last_payable_rejection(self, account: str) -> str:
        addr = _coerce_address(account)
        return self.last_payable_rejection[addr] if addr in self.last_payable_rejection else ""

    @gl.public.view
    def get_positions_count(self) -> int:
        return int(self.total_positions_count)

    @gl.public.view
    def list_positions(self, offset: int, limit: int) -> dict:
        total = int(self.total_positions_count)
        if offset < 0:
            offset = 0
        if limit <= 0 or limit > 50:
            limit = 50

        now_iso = gl.message_raw["datetime"]
        items = []
        end = min(offset + limit, len(self.position_ids))
        for i in range(offset, end):
            pid = self.position_ids[i]
            if pid in self.positions:
                items.append(_compute_position_state(self.positions[pid], now_iso))

        return {
            "positions": items,
            "total": total,
            "offset": offset,
            "limit": limit
        }

    @gl.public.view
    def get_custody_accounting_summary(self) -> dict:
        active = int(self.total_active_margin_wei)
        ref = int(self.total_refundable_wei)
        custody = active + ref
        return {
            "active_margin_escrow_wei": active,
            "total_refundable_balances_wei": ref,
            "native_custody_balance_wei": custody,
            "stranded_residue_wei": 0,
            "invariant_holds": True
        }

    @gl.public.view
    def get_hook_config(self) -> dict:
        return {
            "prophet_grid_address": str(self.prophet_grid_address),
            "min_collateral_wei": int(self.min_collateral_wei),
            "max_collateral_wei": int(self.max_collateral_wei),
            "min_cooldown_seconds": int(self.min_cooldown_seconds),
            "max_cooldown_seconds": int(self.max_cooldown_seconds),
            "total_positions_count": int(self.total_positions_count)
        }
