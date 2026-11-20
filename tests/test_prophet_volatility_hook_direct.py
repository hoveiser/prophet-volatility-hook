import pytest
import json

PROPHET_GRID_ADDR = "0x31C53838fF49168128D772625e34d3D2F7e11116"
MIN_COLLATERAL = 1000000000000000      # 0.001 GEN
MAX_COLLATERAL = 1000000000000000000   # 1.0 GEN
MIN_COOLDOWN = 60                      # 60 seconds
MAX_COOLDOWN = 86400                   # 24 hours

def addr_str(b: bytes) -> str:
    return "0x" + b.hex()

def setup_mock_environment(direct_vm, market_status="OPEN", market_phase="OPEN_WINDOW", refundable=False, can_claim=False, eth_send_fail=False):
    def gl_call_hook(vm, request):
        if "CallContract" in request:
            cc = request["CallContract"]
            calldata_obj = cc.get("calldata", {})
            method = calldata_obj.get("method")
            args = calldata_obj.get("args", [])
            if method == "get_market":
                market_id = args[0] if args else "1"
                market_data = {
                    "market_id": market_id,
                    "question": "Does Python version exceed 3.10?",
                    "status": market_status,
                    "phase": market_phase,
                    "refundable": refundable,
                    "can_claim": can_claim
                }
                from genlayer.py import calldata
                return bytes([0]) + calldata.encode(json.dumps(market_data))
        if "EthSend" in request:
            if eth_send_fail:
                raise RuntimeError("Simulated EOA transfer failure")
            return {"ok": None}
        return None

    direct_vm._gl_call_hook = gl_call_hook

def deploy_hook(direct_deploy, direct_vm, direct_owner, prophet_grid=PROPHET_GRID_ADDR):
    direct_vm.sender = direct_owner
    direct_vm.warp("2026-11-20T10:00:00Z")
    setup_mock_environment(direct_vm)
    return direct_deploy(
        "contracts/prophet_volatility_hook.py",
        prophet_grid,
        MIN_COLLATERAL,
        MAX_COLLATERAL,
        MIN_COOLDOWN,
        MAX_COOLDOWN
    )

def test_constructor_success(direct_vm, direct_deploy, direct_owner):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    config = contract.get_hook_config()
    assert config["prophet_grid_address"].lower() == PROPHET_GRID_ADDR.lower()
    assert config["min_collateral_wei"] == MIN_COLLATERAL
    assert config["max_collateral_wei"] == MAX_COLLATERAL
    assert config["min_cooldown_seconds"] == MIN_COOLDOWN
    assert config["max_cooldown_seconds"] == MAX_COOLDOWN
    assert config["total_positions_count"] == 0

def test_constructor_rejects_zero_min_collateral(direct_vm, direct_deploy, direct_owner):
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("Invalid collateral bounds"):
        direct_deploy("contracts/prophet_volatility_hook.py", PROPHET_GRID_ADDR, 0, MAX_COLLATERAL, MIN_COOLDOWN, MAX_COOLDOWN)

def test_constructor_rejects_inverted_collateral(direct_vm, direct_deploy, direct_owner):
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("Invalid collateral bounds"):
        direct_deploy("contracts/prophet_volatility_hook.py", PROPHET_GRID_ADDR, 200, 100, MIN_COOLDOWN, MAX_COOLDOWN)

def test_constructor_rejects_zero_cooldown(direct_vm, direct_deploy, direct_owner):
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("Invalid cooldown bounds"):
        direct_deploy("contracts/prophet_volatility_hook.py", PROPHET_GRID_ADDR, MIN_COLLATERAL, MAX_COLLATERAL, 0, MAX_COOLDOWN)

def test_constructor_rejects_inverted_cooldown(direct_vm, direct_deploy, direct_owner):
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("Invalid cooldown bounds"):
        direct_deploy("contracts/prophet_volatility_hook.py", PROPHET_GRID_ADDR, MIN_COLLATERAL, MAX_COLLATERAL, 500, 100)

def test_open_margin_success(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = 5000000000000000  # 0.005 GEN

    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 300)
    assert pos_id == "1"

    pos = contract.get_margin_position("1")
    assert pos["position_id"] == "1"
    assert pos["prophet_grid_market_id"] == "1"
    assert pos["posted_collateral_wei"] == 5000000000000000
    assert pos["status"] == "ACTIVE"
    assert pos["reconciled"] is False
    assert contract.get_positions_count() == 1

def test_open_margin_soft_fail_below_min_collateral(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = 100  # below MIN_COLLATERAL

    res = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 300)
    assert res == "REJECTED: COLLATERAL_BELOW_MINIMUM"
    assert contract.get_refundable_balance(addr_str(direct_alice)) == 100
    assert contract.get_last_payable_rejection(addr_str(direct_alice)) == "COLLATERAL_BELOW_MINIMUM"
    assert contract.get_positions_count() == 0

def test_open_margin_soft_fail_empty_market_id(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL

    res = contract.open_volatility_margin_payable("", "https://api.cboe.com/vix", 300)
    assert res == "REJECTED: INVALID_MARKET_ID"
    assert contract.get_refundable_balance(addr_str(direct_alice)) == MIN_COLLATERAL

def test_open_margin_soft_fail_oversized_market_id(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL

    oversized = "m" * 65
    res = contract.open_volatility_margin_payable(oversized, "https://api.cboe.com/vix", 300)
    assert res == "REJECTED: INVALID_MARKET_ID"
    assert contract.get_refundable_balance(addr_str(direct_alice)) == MIN_COLLATERAL

def test_open_margin_soft_fail_invalid_url_scheme(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL

    res = contract.open_volatility_margin_payable("1", "http://insecure.api.com", 300)
    assert res == "REJECTED: INVALID_VOLATILITY_SOURCE_URL"
    assert contract.get_refundable_balance(addr_str(direct_alice)) == MIN_COLLATERAL

def test_open_margin_soft_fail_oversized_url(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL

    oversized_url = "https://example.com/" + ("x" * 250)
    res = contract.open_volatility_margin_payable("1", oversized_url, 300)
    assert res == "REJECTED: INVALID_VOLATILITY_SOURCE_URL"
    assert contract.get_refundable_balance(addr_str(direct_alice)) == MIN_COLLATERAL

def test_open_margin_soft_fail_cooldown_too_short(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL

    res = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 10)
    assert res == "REJECTED: COOLDOWN_OUT_OF_BOUNDS"
    assert contract.get_refundable_balance(addr_str(direct_alice)) == MIN_COLLATERAL

def test_open_margin_soft_fail_cooldown_too_long(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL

    res = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 100000)
    assert res == "REJECTED: COOLDOWN_OUT_OF_BOUNDS"
    assert contract.get_refundable_balance(addr_str(direct_alice)) == MIN_COLLATERAL

def test_open_margin_soft_fail_market_not_found(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)

    def empty_hook(vm, request):
        if "CallContract" in request:
            from genlayer.py import calldata
            return bytes([0]) + calldata.encode("{}")
        return None

    direct_vm._gl_call_hook = empty_hook
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL

    res = contract.open_volatility_margin_payable("999", "https://api.cboe.com/vix", 300)
    assert res == "REJECTED: MARKET_NOT_FOUND_ON_PROPHET_GRID"
    assert contract.get_refundable_balance(addr_str(direct_alice)) == MIN_COLLATERAL

def test_open_margin_soft_fail_grid_revert(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)

    def failing_hook(vm, request):
        if "CallContract" in request:
            raise RuntimeError("RPC error")
        return None

    direct_vm._gl_call_hook = failing_hook
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL

    res = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 300)
    assert res == "REJECTED: FAILED_TO_VERIFY_MARKET_ON_PROPHET_GRID"
    assert contract.get_refundable_balance(addr_str(direct_alice)) == MIN_COLLATERAL

def test_open_margin_overpayment_surplus_credited(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MAX_COLLATERAL + 500000

    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 300)
    assert pos_id == "1"

    pos = contract.get_margin_position("1")
    assert pos["posted_collateral_wei"] == MAX_COLLATERAL
    assert contract.get_refundable_balance(addr_str(direct_alice)) == 500000

def test_open_multiple_positions_different_traders(direct_vm, direct_deploy, direct_owner, direct_alice, direct_bob):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)

    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    id1 = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 300)
    assert id1 == "1"

    direct_vm.sender = direct_bob
    direct_vm.value = MIN_COLLATERAL * 2
    id2 = contract.open_volatility_margin_payable("2", "https://api.cboe.com/vix", 600)
    assert id2 == "2"

    assert contract.get_positions_count() == 2
    p1 = contract.get_margin_position("1")
    p2 = contract.get_margin_position("2")
    assert p1["trader"].lower() == addr_str(direct_alice).lower()
    assert p2["trader"].lower() == addr_str(direct_bob).lower()

def test_evaluate_volatility_regime_calm_band(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    # Warp past cooldown (started at 10:00:00Z)
    direct_vm.warp("2026-11-20T10:05:00Z")

    # Mock web render returning calm vol: 12.5% = 1250 bps
    direct_vm.mock_web(
        r".*cboe.*",
        {"status": 200, "body": '{"volatility_bps": 1250, "status": "LIVE_FEED_MARKET_NORMAL"}'}
    )

    res = contract.evaluate_volatility_regime(pos_id)
    assert res["quantized_vol_bps"] == 1250
    assert res["margin_tier"] == "CALM_LOW_VOL_RELEASE"
    assert res["multiplier_bps"] == 10000

def test_evaluate_volatility_regime_elevated_band(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    direct_vm.warp("2026-11-20T10:05:00Z")
    direct_vm.mock_web(
        r".*cboe.*",
        {"status": 200, "body": '{"volatility_bps": 2000, "status": "LIVE_FEED_MARKET_NORMAL"}'}
    )

    res = contract.evaluate_volatility_regime(pos_id)
    assert res["quantized_vol_bps"] == 2000
    assert res["margin_tier"] == "ELEVATED_BUFFER_HOLD"
    assert res["multiplier_bps"] == 12500

def test_evaluate_volatility_regime_stress_band(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    direct_vm.warp("2026-11-20T10:05:00Z")
    direct_vm.mock_web(
        r".*cboe.*",
        {"status": 200, "body": '{"volatility_bps": 3000, "status": "LIVE_FEED_HIGH_VOLATILITY"}'}
    )

    res = contract.evaluate_volatility_regime(pos_id)
    assert res["quantized_vol_bps"] == 3000
    assert res["margin_tier"] == "STRESS_SURCHARGE_LOCK"
    assert res["multiplier_bps"] == 17500

def test_evaluate_volatility_regime_circuit_breaker_band(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    direct_vm.warp("2026-11-20T10:05:00Z")
    direct_vm.mock_web(
        r".*cboe.*",
        {"status": 200, "body": '{"volatility_bps": 4200, "status": "EXTREME_MARKET_STRESS"}'}
    )

    res = contract.evaluate_volatility_regime(pos_id)
    assert res["quantized_vol_bps"] == 4250
    assert res["margin_tier"] == "CIRCUIT_BREAKER_HALT"
    assert res["multiplier_bps"] == 25000
    assert res["status"] == "CIRCUIT_HALTED"

def test_evaluate_volatility_250bps_quantization_rounding(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    direct_vm.warp("2026-11-20T10:05:00Z")
    # 1840 bps rounds down to 1750 bps (remainder 90 < 125)
    direct_vm.mock_web(
        r".*cboe.*",
        {"status": 200, "body": '{"volatility_bps": 1840, "message": "VIX Index Market Update"}'}
    )
    res1 = contract.evaluate_volatility_regime(pos_id)
    assert res1["quantized_vol_bps"] == 1750

    direct_vm.warp("2026-11-20T10:10:00Z")
    direct_vm.clear_mocks()
    # 1880 bps rounds up to 2000 bps (remainder 130 >= 125)
    direct_vm.mock_web(
        r".*cboe.*",
        {"status": 200, "body": '{"volatility_bps": 1880, "message": "VIX Index Market Update"}'}
    )
    res2 = contract.evaluate_volatility_regime(pos_id)
    assert res2["quantized_vol_bps"] == 2000

def test_evaluate_volatility_fail_closed_empty_response(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    direct_vm.warp("2026-11-20T10:05:00Z")
    direct_vm.mock_web(r".*cboe.*", {"status": 200, "body": ""})

    res = contract.evaluate_volatility_regime(pos_id)
    assert res["margin_tier"] == "CIRCUIT_BREAKER_HALT"
    assert res["status"] == "CIRCUIT_HALTED"
    assert res["multiplier_bps"] == 25000

def test_evaluate_volatility_fail_closed_short_response(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    direct_vm.warp("2026-11-20T10:05:00Z")
    direct_vm.mock_web(r".*cboe.*", {"status": 200, "body": "short text < 32"})

    res = contract.evaluate_volatility_regime(pos_id)
    assert res["margin_tier"] == "CIRCUIT_BREAKER_HALT"
    assert res["status"] == "CIRCUIT_HALTED"

def test_evaluate_volatility_fail_closed_garbage_text(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    direct_vm.warp("2026-11-20T10:05:00Z")
    direct_vm.mock_web(r".*cboe.*", {"status": 200, "body": "This is completely unstructured garbage with no numbers anywhere!"})

    res = contract.evaluate_volatility_regime(pos_id)
    assert res["margin_tier"] == "CIRCUIT_BREAKER_HALT"

def test_evaluate_volatility_rejects_unknown_position(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Position 999 not found"):
        contract.evaluate_volatility_regime("999")

def test_evaluate_volatility_rejects_premature_cooldown(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 3600)

    with direct_vm.expect_revert("Cooldown active"):
        contract.evaluate_volatility_regime(pos_id)

def test_evaluate_volatility_succeeds_after_cooldown_warp(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 3600)

    direct_vm.warp("2026-11-20T12:00:00Z")
    direct_vm.mock_web(r".*cboe.*", {"status": 200, "body": '{"volatility_bps": 1200, "msg": "Calm Market Index Normal"}'})

    res = contract.evaluate_volatility_regime(pos_id)
    assert res["margin_tier"] == "CALM_LOW_VOL_RELEASE"

def test_reconcile_market_margin_state_active_market(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    res = contract.reconcile_market_margin_state(pos_id)
    assert res["reconciled"] is True
    assert res["status"] == "RECONCILED"
    assert "OPEN" in res["reconciled_market_status"]

def test_reconcile_market_margin_state_finalized_market(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    setup_mock_environment(direct_vm, market_status="FINALIZED", market_phase="SETTLED")
    res = contract.reconcile_market_margin_state(pos_id)
    assert res["can_release"] is True
    assert "FINALIZED" in res["reconciled_market_status"]

def test_reconcile_market_margin_state_refundable_market(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    setup_mock_environment(direct_vm, market_status="OPEN", refundable=True)
    res = contract.reconcile_market_margin_state(pos_id)
    assert res["can_refund"] is True

def test_reconcile_market_rejects_unknown_position(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Position 999 not found"):
        contract.reconcile_market_margin_state("999")

def test_settle_or_release_margin_calm_regime_success(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    direct_vm.warp("2026-11-20T10:05:00Z")
    direct_vm.mock_web(r".*cboe.*", {"status": 200, "body": '{"volatility_bps": 1000, "msg": "Calm Market Index Normal"}'})
    contract.evaluate_volatility_regime(pos_id)
    contract.reconcile_market_margin_state(pos_id)

    res = contract.settle_or_release_margin(pos_id)
    assert res == f"RELEASED:{MIN_COLLATERAL}"

    pos = contract.get_margin_position(pos_id)
    assert pos["status"] == "RELEASED"

def test_settle_or_release_margin_finalized_market_success(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    setup_mock_environment(direct_vm, market_status="FINALIZED", market_phase="SETTLED")
    contract.reconcile_market_margin_state(pos_id)

    res = contract.settle_or_release_margin(pos_id)
    assert res == f"RELEASED:{MIN_COLLATERAL}"

def test_settle_or_release_margin_rejects_unreconciled(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    with direct_vm.expect_revert("Cross-contract reconciliation required"):
        contract.settle_or_release_margin(pos_id)

def test_settle_or_release_margin_rejects_elevated_unfinalized(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    contract.reconcile_market_margin_state(pos_id)
    with direct_vm.expect_revert("Margin release criteria not satisfied"):
        contract.settle_or_release_margin(pos_id)

def test_settle_or_release_margin_rejects_circuit_halted(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    direct_vm.warp("2026-11-20T10:05:00Z")
    direct_vm.mock_web(r".*cboe.*", {"status": 200, "body": '{"volatility_bps": 4000, "msg": "Circuit Breaker Triggered"}'})
    contract.evaluate_volatility_regime(pos_id)

    setup_mock_environment(direct_vm, market_status="OPEN", market_phase="ACTIVE")
    contract.reconcile_market_margin_state(pos_id)

    with direct_vm.expect_revert("Margin release criteria not satisfied"):
        contract.settle_or_release_margin(pos_id)

def test_settle_or_release_margin_rejects_double_release(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    setup_mock_environment(direct_vm, market_status="FINALIZED", market_phase="SETTLED")
    contract.reconcile_market_margin_state(pos_id)
    contract.settle_or_release_margin(pos_id)

    with direct_vm.expect_revert("Position already settled"):
        contract.settle_or_release_margin(pos_id)

def test_claim_position_refund_expired_market_success(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    setup_mock_environment(direct_vm, market_status="OPEN", refundable=True)
    contract.reconcile_market_margin_state(pos_id)

    res = contract.claim_position_refund(pos_id)
    assert res == f"REFUNDED:{MIN_COLLATERAL}"

    pos = contract.get_margin_position(pos_id)
    assert pos["status"] == "REFUNDED"

def test_claim_position_refund_rejects_unreconciled(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    with direct_vm.expect_revert("Cross-contract reconciliation required"):
        contract.claim_position_refund(pos_id)

def test_claim_position_refund_rejects_non_refundable_market(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    setup_mock_environment(direct_vm, market_status="OPEN", refundable=False)
    contract.reconcile_market_margin_state(pos_id)

    with direct_vm.expect_revert("Market does not qualify for refund"):
        contract.claim_position_refund(pos_id)

def test_withdraw_refundable_balance_success(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = 100  # rejected, credited to refundable
    contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    bal_before = contract.get_refundable_balance(addr_str(direct_alice))
    assert bal_before == 100

    withdrawn = contract.withdraw_refundable_balance(50)
    assert withdrawn == 50

    bal_after = contract.get_refundable_balance(addr_str(direct_alice))
    assert bal_after == 50

def test_withdraw_refundable_balance_rejects_zero_or_negative(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Amount must be positive"):
        contract.withdraw_refundable_balance(0)

def test_withdraw_refundable_balance_rejects_excessive_amount(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = 100
    contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    with direct_vm.expect_revert("Insufficient refundable balance"):
        contract.withdraw_refundable_balance(200)

def test_claim_all_refundable_balance_zero_returns_zero(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    assert contract.claim_all_refundable_balance() == 0

def test_claim_all_refundable_balance_success(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = 500
    contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    withdrawn = contract.claim_all_refundable_balance()
    assert withdrawn == 500
    assert contract.get_refundable_balance(addr_str(direct_alice)) == 0

def test_zero_wei_stranded_residue_accounting_invariant(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)

    # Initial state
    inv0 = contract.get_custody_accounting_summary()
    assert inv0["native_custody_balance_wei"] == 0
    assert inv0["stranded_residue_wei"] == 0

    # 1 rejection (credited to refundable)
    direct_vm.sender = direct_alice
    direct_vm.value = 500
    contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)
    inv1 = contract.get_custody_accounting_summary()
    assert inv1["total_refundable_balances_wei"] == 500
    assert inv1["active_margin_escrow_wei"] == 0
    assert inv1["native_custody_balance_wei"] == 500

    # 1 valid position
    direct_vm.value = MIN_COLLATERAL
    contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)
    inv2 = contract.get_custody_accounting_summary()
    assert inv2["total_refundable_balances_wei"] == 500
    assert inv2["active_margin_escrow_wei"] == MIN_COLLATERAL
    assert inv2["native_custody_balance_wei"] == MIN_COLLATERAL + 500
    assert inv2["stranded_residue_wei"] == 0

def test_list_positions_pagination(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL

    contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)
    contract.open_volatility_margin_payable("2", "https://api.cboe.com/vix", 60)
    contract.open_volatility_margin_payable("3", "https://api.cboe.com/vix", 60)

    page1 = contract.list_positions(0, 2)
    assert len(page1["positions"]) == 2
    assert page1["total"] == 3

    page2 = contract.list_positions(2, 2)
    assert len(page2["positions"]) == 1
    assert page2["positions"][0]["position_id"] == "3"

def test_get_last_payable_rejection(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    assert contract.get_last_payable_rejection(addr_str(direct_alice)) == ""

    direct_vm.value = 50
    contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)
    assert contract.get_last_payable_rejection(addr_str(direct_alice)) == "COLLATERAL_BELOW_MINIMUM"

def test_evaluate_volatility_rejects_already_released_position(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    setup_mock_environment(direct_vm, market_status="FINALIZED", market_phase="SETTLED")
    contract.reconcile_market_margin_state(pos_id)
    contract.settle_or_release_margin(pos_id)

    with direct_vm.expect_revert("does not allow evaluation"):
        contract.evaluate_volatility_regime(pos_id)

def test_claim_position_refund_rejects_already_refunded_position(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    setup_mock_environment(direct_vm, market_status="OPEN", refundable=True)
    contract.reconcile_market_margin_state(pos_id)
    contract.claim_position_refund(pos_id)

    with direct_vm.expect_revert("Position already settled"):
        contract.claim_position_refund(pos_id)

def test_payout_delivery_failure_preserves_refundable_balance(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = 100
    contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    # Reconfigure mock to fail on EthSend
    setup_mock_environment(direct_vm, eth_send_fail=True)

    with direct_vm.expect_revert("Transfer failed, refundable balance restored"):
        contract.withdraw_refundable_balance(50)

    # Verify balance was preserved intact
    assert contract.get_refundable_balance(addr_str(direct_alice)) == 100
    summary = contract.get_custody_accounting_summary()
    assert summary["total_refundable_balances_wei"] == 100

def test_settle_release_delivery_failure_preserves_funds(direct_vm, direct_deploy, direct_owner, direct_alice):
    contract = deploy_hook(direct_deploy, direct_vm, direct_owner)
    direct_vm.sender = direct_alice
    direct_vm.value = MIN_COLLATERAL
    pos_id = contract.open_volatility_margin_payable("1", "https://api.cboe.com/vix", 60)

    setup_mock_environment(direct_vm, market_status="FINALIZED", market_phase="SETTLED")
    contract.reconcile_market_margin_state(pos_id)

    # Reconfigure mock to fail on EthSend
    setup_mock_environment(direct_vm, market_status="FINALIZED", market_phase="SETTLED", eth_send_fail=True)
    contract.settle_or_release_margin(pos_id)

    # Payout delivery failure credited funds to refundable_balances
    assert contract.get_refundable_balance(addr_str(direct_alice)) == MIN_COLLATERAL
    summary = contract.get_custody_accounting_summary()
    assert summary["total_refundable_balances_wei"] == MIN_COLLATERAL
    assert summary["stranded_residue_wei"] == 0
