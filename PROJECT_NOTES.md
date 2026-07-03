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
Two cron scripts share thresholds so they never fight:
- **`startWP.py`** — turns the `.68` enable relay ON when: solar surplus
  (`solar_total >= solar_prod_level` AND `usage < actual_use_limit`) OR tank
  `< min_temp` (50 °C hot-water floor).
- **`stopWP.py`** — drops `.68` only when idle + no sun + tank warm. SAFETY: never
  aborts a running compressor (detected via `temp_speicher` / Vorlauf rising ≥ 0.3 °C
  over ~6 min). Immune to cooking load (the old `sum > 1000 W` bug).

History: the evening heating was ultimately caused by the pump being **physically
switched to autonomous mode** (ran on its own thermostat regardless of `.68`). On
2026-07-03 it was switched back to follow the scripts. The rewrite still stands.

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
- Add panels via API: `POST /api/dashboards/db` with `{"dashboard":<model>,"overwrite":true}`,
  Bearer = a service-account **Editor** token. Always APPEND (new ids, high gridPos.y);
  never rewrite existing panels.

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

### Month / year SQL filters
- Month: `stamp like concat(FROM_UNIXTIME(UNIX_TIMESTAMP(),'%Y-%m'),'%')`
- Year:  `stamp like concat(FROM_UNIXTIME(UNIX_TIMESTAMP(),'%Y'),'%')`

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
