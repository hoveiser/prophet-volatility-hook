# Adversarial Security Review: ProphetVolatilityHook

Review Date: 2026-11-20
Contract: `contracts/prophet_volatility_hook.py`
Deployed Address: `0x50C948FD62034cEe92C161411D7c7c1737511666`
Ecosystem Target: ProphetGrid (`0x31C53838fF49168128D772625e34d3D2F7e11116`)

---

## 1. State Machine Table

| Current Status | Method | Caller | Next Status | Fund Movement | Guards |
|----------------|--------|--------|-------------|---------------|--------|
| (None) | `open_volatility_margin_payable` | Any Trader | `ACTIVE` | Staked collateral into `total_active_margin_wei`; surplus into `refundable_balances` | Valid market ID on ProphetGrid, valid HTTPS URL, bounds check |
| (None) | `open_volatility_margin_payable` (Validation Failed) | Any Caller | (No position created) | 100% of sent value credited to `refundable_balances[caller]` | Soft-fail payable pattern (never reverts, 0 wei trapped) |
| `ACTIVE` | `evaluate_volatility_regime` | Any Caller | `ACTIVE` or `CIRCUIT_HALTED` | None | Cooldown elapsed (`now >= ref + cooldown`). Binds discrete 250-bps quantized band |
| `ACTIVE` / `CIRCUIT_HALTED` | `reconcile_market_margin_state` | Any Caller | `RECONCILED` / `CIRCUIT_HALTED` | None | Queries ProphetGrid `get_market(market_id)` |
| `RECONCILED` | `settle_or_release_margin` | Trader / Anyone | `RELEASED` | `posted_collateral_wei` paid out to `pos.trader` via `IEoaRecipient` | Must be reconciled; CALM regime or finalized market |
| `RECONCILED` | `claim_position_refund` | Trader / Anyone | `REFUNDED` | `posted_collateral_wei` refunded to `pos.trader` via `IEoaRecipient` | Must be reconciled; ProphetGrid market refundable/expired |
| Any | `withdraw_refundable_balance` | Claimant EOA | Unchanged | Withdrawn amount paid out to claimant EOA | `amount > 0` and `amount <= refundable_balances[caller]` |

---

## 2. Liveness: No Stuck Funds

- Rejection Path: If a payable deposit fails any validation check, 100% of sent funds are immediately credited to `refundable_balances[sender]`. The claimant can withdraw them at any time via `withdraw_refundable_balance` or `claim_all_refundable_balance`.
- Overpayment Path: If a trader posts collateral exceeding `max_collateral_wei`, the surplus is credited to `refundable_balances[sender]` without trapping funds.
- Active Margin Path:
  - If market is normal and volatility is calm, `settle_or_release_margin` releases principal to trader.
  - If market terminates, settles, expires, or is refunded on ProphetGrid, cross-contract reconciliation enables `settle_or_release_margin` or `claim_position_refund` to return 100% principal to the trader.
  - If recipient delivery fails during EOA payout, funds are credited back to `refundable_balances[pos.trader]`, ensuring funds are never burned or stuck.

---

## 3. Race Conditions and Transition Independence

- Mutually Exclusive Settlement: A position can only be settled or refunded once. Both `settle_or_release_margin` and `claim_position_refund` verify `pos.status not in ("RELEASED", "REFUNDED")` and update status before external interaction.
- Reconciliation Gate: Margin release requires `pos.reconciled == True`. A trader cannot bypass live ecosystem verification against ProphetGrid.
- Temporal Cooldown vs Re-evaluation: Cooldown is calculated strictly from message timestamps (`gl.message_raw["datetime"]`) comparing `now_epoch >= ref_epoch + cooldown`, preventing evaluation spam.

---

## 4. Accounting Invariants

- Core Invariant:
  `native_custody_balance_wei == active_margin_escrow_wei + total_refundable_balances_wei`
- Zero Stranded Residue:
  Every wei that enters via `gl.message.value` is accounted for in either active margin or refundable balances.
  Every wei withdrawn is deducted from the exact balance.
  `stranded_residue_wei` is strictly 0 at all times.
- Verified on Studionet:
  `{"active_margin_escrow_wei": 5000000000000000, "total_refundable_balances_wei": 0, "native_custody_balance_wei": 5000000000000000, "stranded_residue_wei": 0, "invariant_holds": true}`

---

## 5. Input Validation

- Collateral Bounds: Constructor enforces `0 < min_collateral_wei <= max_collateral_wei`.
- Cooldown Bounds: Constructor enforces `0 < min_cooldown_seconds <= max_cooldown_seconds`.
- Market ID: Non-empty string with maximum length of 64 characters.
- Volatility URL: Enforces `https://` prefix and maximum length of 256 characters.
- Withdrawal Amounts: Enforces `amount > 0` and `amount <= refundable_balances[caller]`.

---

## 6. Consensus Safety and Grid Quantization

- 250-bps Grid Quantization:
  Implied volatility readings are quantized onto discrete multiples of 250 bps (`quantized_bps = (extracted // 250) * 250 (+ 250 if remainder >= 125)`).
- 4 Discrete Regime Bands:
  - `CALM_LOW_VOL_RELEASE` (< 1500 bps): 10000 bps multiplier (1.00x).
  - `ELEVATED_BUFFER_HOLD` (1500 to 2499 bps): 12500 bps multiplier (1.25x).
  - `STRESS_SURCHARGE_LOCK` (2500 to 3499 bps): 17500 bps multiplier (1.75x).
  - `CIRCUIT_BREAKER_HALT` (>= 3500 bps): 25000 bps multiplier (2.50x).
- Fail-Closed Protection:
  Empty responses, responses < 32 characters, non-numeric content, or network exceptions automatically bind to `CIRCUIT_BREAKER_HALT` with maximum buffer protection.
- Validator Agreement:
  `gl.eq_principle.prompt_comparative` requires 100% exact match on discrete regime band, quantized volatility bps, and multiplier bps.

---

## 7. Review Findings

| Finding ID | Severity | Description | Status | Proving Test |
|------------|----------|-------------|--------|--------------|
| SEC-01 | HIGH | Revert in payable method could strand user transaction value | FIXED | `test_open_margin_soft_fail_below_min_collateral` |
| SEC-02 | HIGH | Unchecked external market existence could open orphan margin positions | FIXED | `test_open_margin_soft_fail_market_not_found` |
| SEC-03 | MEDIUM | Flaky web feed could cause validator disagreement | FIXED | `test_evaluate_volatility_fail_closed_empty_response`, `test_evaluate_volatility_fail_closed_short_response` |
| SEC-04 | MEDIUM | Premature re-evaluation race before market stabilization | FIXED | `test_evaluate_volatility_rejects_premature_cooldown` |
| SEC-05 | HIGH | EOA transfer failure during payout could permanently lose principal | FIXED | `test_payout_delivery_failure_preserves_refundable_balance`, `test_settle_release_delivery_failure_preserves_funds` |
| SEC-06 | LOW | Rounding residue during continuous basis points calculation | FIXED | `test_zero_wei_stranded_residue_accounting_invariant` |
