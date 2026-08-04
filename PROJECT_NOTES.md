# dsnj-homie — Solar / Heat-pump control & Grafana notes

Handoff document so we can continue next time. Last updated 2026-07-03.

## 1. What this repo does
Home IoT scripts (run via cron) that poll Shelly devices, store readings in a local
MySQL DB (`solar`), control the heat pump (WP), and feed a Grafana dashboard.

- DB access is via `config.py` (git-ignored, holds `DB_NAME/DB_USER/DB_PASS`).
  Copy `config.example.py` → `config.py` to set up.
- Grafana runs on `localhost:3000` (v9.2.3), proxied by both `solar.linuxkiste.ch`
  and `home.linuxkiste.ch`. Admin user `leinad`, read-only `viewer`.

## 2. Heat-pump (WP) control
Two cron scripts share thresholds so they never fight. Both run **24/7**
(`startWP` `*/5 * * * *`, `stopWP` `*/15 * * * *`):
- **`startWP.py`** — turns the `.68` enable relay ON when: solar surplus
  (`solar_total >= solar_prod_level` AND `usage < actual_use_limit`) OR tank
  `< min_temp` (50 °C hot-water floor). Running 24/7 is safe: the solar branch
  can't fire at night (the 3EM reads ~−5 W), so overnight it only enforces the floor.
  - **Adaptive `solar_prod_level` (2026-08-04):** no longer a fixed 1300 W. Now
    `compute_adaptive_prod_level()` = `PEAK_FACTOR(0.78) × avg of the last 10 daily
    peaks` (`get_avg_daily_peak`, `GREATEST(sol_w,0)` grouped by day), clamped to
    `PROD_LEVEL_FLOOR..CAP` = **800–5000 W**. So the pump only starts near the recent
    daily peak (≈4800 W now → PV nearly covers the ~3.3–4.8 kW compressor) instead of
    dribbling in at 1300 W in the early morning. It self-lowers as autumn peaks fall.
    Falls back to the static default if PV data is missing. NOTE: in CH the daily
    *peak power* stays high through late summer (it's daily *energy*/day-length that
    shrinks), so the threshold holds ~4800 into Sept and only drops steeply Oct–Dec.
    SAFETY: this only gates the *solar* start — the 50 °C hot-water floor is separate
    and always fires, so the pump can never be locked out.
    The value is logged every run to `wp_decision.solar_prod_level` (Grafana panel 91).
  - **`stopWP.py` uses the SAME adaptive bar (2026-08-04):** it too now calls
    `compute_adaptive_prod_level()` for "sun present", so the enable is held ON only
    while PV is near the recent daily peak (~4800 W) instead of all day above a fixed
    1300 W. A running compressor is still protected by `isHeating()` (never abort
    mid-cycle) and the comfort floor still guarantees hot water, so the higher bar
    can't short-cycle or leave the tank cold. Net effect: the pump is enabled roughly
    only in the strong-sun window around midday (+ the two exceptions).
  - **Afternoon fallback (2026-08-04):** `afternoon_fallback_level()` in BOTH scripts.
    On a day whose peak underdelivers (worse than the 10-day avg the bar rides on) PV
    never reaches ~4800 W, so the pump would skip solar and grid-heat at night. Fix:
    wait for the peak until `PEAK_HOUR` (13:00), then - only if the tank still wants
    solar heat (`< SOLAR_TARGET_TEMP` 58 °C, which a normal sunny day already passed) -
    step the bar linearly down to `FALLBACK_MIN_LEVEL` (1500 W) by `FALLBACK_END_HOUR`
    (17:00), grabbing the best remaining sun. STATELESS: the tank temp is the "did we
    capture sun today" signal - no history query. Applied in start AND stop (same curve)
    or they'd ping-pong. Data behind it: clouds_all correlates only +0.49 with daily
    PEAK power (bursty cloudy days still peak >5 kW) but −0.55 with daily kWh, so a
    forecast-driven power cut is a blunt tool; the tank-temp fallback targets the real
    loss (a single below-average day amid good ones). The older "clear now, cloudy
    later → −`red_for_bad_weather`" reduction is kept (fires in the morning, complementary).
- **`stopWP.py`** — drops `.68` only when idle + no sun + tank warm. SAFETY: never
  aborts a running compressor. "Running" = tank `temp_speicher` rising ≥ 0.3 °C over
  ~6 min **OR** total house draw ≥ `pump_power_level` (3000 W). The pump pulls
  ~3.3–4.8 kW, well above cooking (~2.4 kW) and standby (~0.3 kW), and the power
  signal leads the tank by ~4 min. The Vorlauf (space-heating flow) sensors were
  **dropped** — they drift on their own in summer and gave false "heating" readings.

Both scripts wrap the Shelly meter reads in `try/except` with `timeout=10`: a LAN
blip now logs a warning and skips the run (relay untouched, next tick retries)
instead of crashing.

History: the evening heating was ultimately caused by the pump being **physically
switched to autonomous mode** (ran on its own thermostat regardless of `.68`). On
2026-07-03 it was switched back to follow the scripts. On **2026-07-04** the pump
still grid-heated at 03:00 because `.68` was left enabled overnight (false Vorlauf
"heating" at 23:00 + two crashed stop runs + no cron coverage 23:00→09:00); all
three were fixed (isHeating rewrite, network guards, 24/7 schedule). Rewrite stands.

## 3. WP decision logging (added 2026-07-03)
Both scripts call `log_decision()` → inserts one row per run into MySQL table
**`wp_decision`** so Grafana can show *why* the pump switched.

```sql
CREATE TABLE wp_decision (
  id INT AUTO_INCREMENT PRIMARY KEY,
  ts DATETIME NOT NULL,
  script VARCHAR(8),        -- 'start' | 'stop'
  action VARCHAR(16),       -- 'enabled' | 'no_start' | 'kept_on' | 'disabled'
  relay VARCHAR(4),         -- 'on' | 'off' | NULL
  tank DOUBLE, solar_total DOUBLE, netz_total DOUBLE, actual_usage DOUBLE,
  solar_prod_level INT, sun_present TINYINT(1), heating TINYINT(1),
  reason VARCHAR(255), KEY idx_ts (ts)
);
```
Backfilled from `controlWP.log` (only post-rewrite lines from 2026-07-02 match).

## 4. Grafana dashboard "solar dashboard"
- Dashboard uid **`CzWLWUbMz`**, MySQL datasource uid **`bZZ3Wdt7k`** (name "MySQL", db `solar`).
- Add panels via API: `POST /api/dashboards/db`, Bearer = a service-account **Editor** token.
  Always APPEND (new ids, high gridPos.y). **CONCURRENCY:** the user edits/arranges the dashboard
  in the UI live. Do NOT blindly `overwrite:true` on a stale model — re-fetch immediately before
  writing, keep the fetched `version`, post with `overwrite:false`, and retry on a 412 conflict.
  (A clobber happened 2026-07-04; recovered via `/api/dashboards/uid/:uid/versions/:v`.)

Panels added this session (66–76, all at the bottom, existing panels untouched):
| id | panel |
|----|-------|
| 66 | WP – Entscheidung (warum an/aus) — state-timeline of `wp_decision.action` |
| 67 | Solar produziert (Monat) |
| 68 | Elektra bezogen (Monat) |
| 69 | Eigenanteil (Monat) |
| 70 | Solarproduktion pro Monat (bar chart, current year) |
| 71 | Solar-Ertrag (Monat) CHF |
| 72 | Elektra Energiekosten (Monat) CHF |
| 73 | Solar-Ertrag (Jahr) CHF |
| 74 | Elektra Energiekosten (Jahr) CHF |
| 75 | Bezugspreis (elektrasolar+, inkl. MWST) 29.87 Rp/kWh |
| 76 | Einspeise-Vergütung (Q1 2026, inkl. HKN) 12.27 Rp/kWh |

Panels added/changed 2026-07-04 (all use the swap-safe `sol_w` methodology, see §5):
| id | panel |
|----|-------|
| 77 | Eigenanteil pro Jahr (bar, ab 2025) — self/**production** |
| 78 | Elektra Energiekosten pro Jahr (bar, ab 2025) CHF |
| 79 | Stromverbrauch Haus pro Jahr (bar, ab 2025) kWh |
| 80/81 | Effektive Stromkosten (Monat/Jahr) = Energiekosten − Solar-Ertrag; grün<0/rot≥0 |
| 82 | Hausverbrauch/Monat gestapelt: Eigen(Solar) vs Elektra, kWh (ab 2025) |
| 83 | dito als **%**-Anteil (jeder Balken = 100 %) |
| 84 | Hausverbrauch/**Tag** gestapelt (letzte 30 Tage) |
| 91 | **WP – Solar-Start-Schwelle (adaptiv, W)** — time series of `wp_decision.solar_prod_level` (2026-08-04) |
| Autarkie today/yesterday/(Monat) (38/39/69) | old EA panels: **corrected to `sol_w`** + **renamed "Autarkie"** (user later pruned the 2025/30d/¼y/½y/year-back variants) |

### Eigenanteil vs. Autarkie (two distinct KPIs — do not conflate)
- **Eigenanteil / Eigenverbrauchsquote** = Eigenverbrauch / **Produktion** = (prod−feedin)/prod.
  Only panel **77** ("Eigenanteil pro Jahr"). 2025 = 32.9 %.
- **Autarkiegrad** = Eigenverbrauch / **Hausverbrauch** = (prod−feedin)/((prod−feedin)+import).
  The "Autarkie …" panels (currently today/yesterday/Monat). 2025 = 20.7 %.
- Same numerator (self-consumed solar), different denominator. Autarkie<Eigenanteil here because
  the house consumes more than the PV produces per year (2025: 14 660 vs 9 219 kWh).

### Month / year SQL filters
- Month: `stamp like concat(FROM_UNIXTIME(UNIX_TIMESTAMP(),'%Y-%m'),'%')`
- Year:  `stamp like concat(FROM_UNIXTIME(UNIX_TIMESTAMP(),'%Y'),'%')`
- „ab 2025": `stamp >= '2025-01-01'` grouped `YEAR(stamp)` / `DATE_FORMAT(stamp,'%Y-%m')`.

## 5. Energy data quality — IMPORTANT
The `shelly_solar` energy columns are unreliable:
- **`sol_wh_consumed_diff` / `sol_wh_returned_diff` are corrupted** by the 2026-07 PV meter
  swap (read ~50–75× too high; spurious spikes). **Do NOT use them for production.**
- Collection has gaps — **June 2026 missing entirely**; only Jul 2 onward this month.
- Grid columns (`elektra_wh_*_diff`) are fine once spikes filtered (`BETWEEN 0 AND 1000`).

**Correct methodology (what the new panels use):**
- PV production (kWh) = `SUM(GREATEST(sol_w,0))/60/1000` (÷60 = 1-min samples). Swap-proof.
- Grid import from Elektra = spike-filtered `elektra_wh_consumed_diff`.
- Grid export (feed-in) = spike-filtered `elektra_wh_returned_diff`.
- Self-consumed = production − export;  House use = self-consumed + import.
- Eigenanteil = self-consumed / house-use × 100.

## 6. Elektra Jegenstorf tariffs 2026 (elektra.ch)
Products from invoices: network **elektra b**, energy **elektrasolar+**. Flat 0–24h (no HT/NT).
- **Bezug (buy): 29.87 Rp/kWh incl. MWST** = 0.2987 CHF/kWh
  (Energie 16.65 + Netz 9.95 + Netzzuschlag 2.49 + reserves).
  Fixed: Grundpreis 4.32 + Messpreis 7.03 CHF/month + small Gemeindeabgabe.
- **Einspeisung (feed-in) Q1 2026: 12.27 Rp/kWh** = 0.12266 CHF/kWh
  (Wirkenergie 10.266 + HKN 2.00, excl. MWST — household not MWST-pflichtig; HKN only with
  elektrasolar+). Q2–Q4 set quarterly via Referenzmarktpreis (not yet published).

CHF formulas in panels:
- Solar-Ertrag = Eigenverbrauch × 0.2987 + Überschuss × 0.12266
- Elektra-Kosten = Netzbezug × 0.2987

## 7. Open TODOs
1. **Fix the corrupted solar production pipeline** (`fetch3EMSolar.py` / meter swap) so the
   *existing* "Solar Today"/"EA" panels stop showing garbage (today ≈376 kWh, month EA ≈ −40 %).
   Only the solar meter was swapped; grid columns are fine.
2. **Measure the WP rewrite impact** once a week of clean data exists: grep "WP disabled" in
   controlWP.log; check for evening `temp_speicher` rises; compare evening grid import.
3. Update feed-in tariff when Elektra publishes Q2–Q4 (currently using Q1 rate).
4. Backfill is only ~1.5 days for July; year figures understated by the Apr–Jun data gap.

## 8. Continuing with Grafana
Create a service-account **Editor** token in Grafana (Configuration → Service accounts) and
use it as `Authorization: Bearer <token>` against `http://localhost:3000/api/...`.
Revoke by deleting the service account.
</content>
