# ProphetVolatilityHook

Dynamic Margin & Implied Volatility Circuit-Breaker Hook for the **ProphetGrid** flagship ecosystem on GenLayer.

[![GenLayer Studionet](https://img.shields.io/badge/GenLayer-Studionet-blue)](https://studio.genlayer.com)
[![Runner](https://img.shields.io/badge/Runner-py--genlayer%3A1jb45aa8...-green)](contracts/prophet_volatility_hook.py)
[![Tests](https://img.shields.io/badge/Tests-54%20Passing-brightgreen)](tests/test_prophet_volatility_hook_direct.py)
[![Chain ID](https://img.shields.io/badge/Chain%20ID-61999-orange)](https://studio.genlayer.com/api)

---

## 1. Overview

`ProphetVolatilityHook` is an Intelligent Contract designed to provide dynamic margin buffers and automated circuit-breaking capabilities for prediction and derivative markets hosted on `ProphetGrid` (`0x31C53838fF49168128D772625e34d3D2F7e11116`).

The contract enables traders and liquidity providers to stake native GEN margin collateral linked to specific ProphetGrid market identifiers and institutional volatility feeds. Through GenLayer web consensus, validators independently render external market feeds, quantize volatility readings onto a discrete 250-bps grid, and enforce four deterministic regime bands.

---

## 2. On-Chain Deployment & Verification

| Property | Value |
|----------|-------|
| Network | GenLayer Studionet |
| Chain ID | 61999 |
| Contract Name | ProphetVolatilityHook |
| Contract Address | `0x50C948FD62034cEe92C161411D7c7c1737511666` |
| ProphetGrid Target | `0x31C53838fF49168128D772625e34d3D2F7e11116` |
| Deploy Transaction | `0x507273e8c827f25402521232336521c77a77196f3d8e8479af8eb78ecf35d5fb` |
| Deploy Status | FINALIZED |
| Runner Dependency | `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6` |
| Source LF SHA-256 | `5875cbc7386e615ac532bc8aceb1ce4da1762f05cb9f6d12e6e5c3ad8e51b653` |

Full deployment and on-chain verification logs are recorded in [docs/deployment.md](docs/deployment.md).

---

## 3. Core Architecture & Ecosystem Integration

### Cross-Contract Interaction with ProphetGrid
When a margin position is opened, `ProphetVolatilityHook` performs a live view call to `ProphetGrid.get_market(market_id)` to verify the target market exists and is active. Before any margin buffer can be released or settled, `reconcile_market_margin_state` must be executed to reconcile on-chain state against ProphetGrid.

### 250-bps Grid Quantization & Consensus Regime Bands
External implied volatility readings are parsed and quantized onto a discrete 250-bps grid:
`quantized_bps = (extracted // 250) * 250 (+ 250 if remainder >= 125)`

Validators evaluate external data through `gl.nondet.web.render` and agree with 100% consensus in `gl.eq_principle.prompt_comparative` on one of four discrete regime bands:

1. `CALM_LOW_VOL_RELEASE` (< 1500 bps): Multiplier is 10000 bps (1.00x). Margin buffer is eligible for release.
2. `ELEVATED_BUFFER_HOLD` (1500 to 2499 bps): Multiplier is 12500 bps (1.25x). Collateral buffer is held.
3. `STRESS_SURCHARGE_LOCK` (2500 to 3499 bps): Multiplier is 17500 bps (1.75x). Surcharge locked, additional buffer required.
4. `CIRCUIT_BREAKER_HALT` (>= 3500 bps): Multiplier is 25000 bps (2.50x). Position is locked under circuit breaker.

### Fail-Closed Web Handling
If the external feed returns an empty response, content shorter than 32 characters, unparseable data, or raises an HTTP error, the contract automatically fails closed to `CIRCUIT_BREAKER_HALT` with maximum buffer protection.

### Real Native Custody Accounting & Soft-Fail Payable
The contract implements strict conservation of native GEN:
`native_custody_balance_wei == active_margin_escrow_wei + total_refundable_balances_wei`

- Never Revert in Payable Methods: If validation fails in `open_volatility_margin_payable`, 100% of sent value is credited to `refundable_balances[sender]` and recorded in `last_payable_rejection[sender]`.
- Overpayment Protection: Any deposit exceeding `max_collateral_wei` has its surplus credited directly to `refundable_balances[sender]`.
- Safe Payouts: Payouts and withdrawals are transferred via `IEoaRecipient.emit_transfer`. If delivery fails, the balance is restored to prevent loss of funds.
- Zero Wei Stranded Residue: Residual balances are strictly 0 wei at all times.

---

## 4. State Machine Table

| Current Status | Method | Caller | Next Status | Fund Movement |
|----------------|--------|--------|-------------|---------------|
| (Unfunded) | `open_volatility_margin_payable` | Trader | `ACTIVE` | Collateral locked in active escrow |
| `ACTIVE` | `evaluate_volatility_regime` | Anyone | `ACTIVE` / `CIRCUIT_HALTED` | Evaluates live web feed, updates multiplier |
| `ACTIVE` / `CIRCUIT_HALTED` | `reconcile_market_margin_state` | Anyone | `RECONCILED` / `CIRCUIT_HALTED` | Reads live market status from ProphetGrid |
| `RECONCILED` | `settle_or_release_margin` | Trader / Anyone | `RELEASED` | Principal paid out to trader EOA |
| `RECONCILED` | `claim_position_refund` | Trader / Anyone | `REFUNDED` | 100% principal refunded on market expiry/timeout |
| Any | `withdraw_refundable_balance` | Claimant | Unchanged | Refundable balance transferred to caller EOA |

---

## 5. Testing & Verification

The suite includes 54 comprehensive unit tests in `tests/test_prophet_volatility_hook_direct.py` covering all edge cases, access controls, soft-fail payable mechanisms, discrete grid quantization, and accounting invariants.

Run linter:
```bash
genvm-lint check contracts/prophet_volatility_hook.py
```

Run test suite:
```bash
pytest tests/ -q
```
Result: 54 passed in 5.12s (100% pass rate).

---

## 6. Security & Adversarial Review

An adversarial security review was performed covering stuck fund prevention, race conditions, consensus safety, and invariant enforcement. Detailed notes are available in [docs/adversarial-review.md](docs/adversarial-review.md).
