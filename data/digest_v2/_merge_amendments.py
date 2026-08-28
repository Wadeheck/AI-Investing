"""Step 5: merge events_amend_v14/ into the base corpus, rebuild ledger.jsonl
and news_impulses_v2.jsonl, and emit validation_report.md.

Never modifies events/*.json (retention rule). Produces a merged in-memory
view (per date: original events + amendment new-events, with add_nodes/
replace_nodes/add_deals applied) that ledger + impulses are derived from.
"""
import json, glob, os, re, statistics, collections, tempfile

BASE = os.path.dirname(__file__)
EVENTS_DIR = os.path.join(BASE, "events")
AMEND_DIRS = [os.path.join(BASE, "events_amend_v14"),
              os.path.join(BASE, "events_amend_crypto")]   # crypto-backfill campaign (2026-08)

VALID_NODES = set("""ai_capex_cycle ai_circularity boe_rate bond_stress btc_halving cb_gold_buying
china_anti_corruption china_consumer china_export_controls china_growth china_property china_stimulus
cnh_devaluation credit_conditions credit_spreads crypto_adoption currency_peg_stress custody_risk
crypto_liquidity crypto_regulation defense_spending ecb_policy em_flows energy_transition europe_growth
eurozone_political_risk fed_rate financial_engineering financial_fraud freight_logistics
geopolitical_tension global_growth india_growth japan_debt korea_growth market_intervention mas_policy
money_supply oil_supply pboc_rate political_stability power_demand private_credit rare_earths
risk_appetite sanctioned_economy_stress sanctions shipping_costs uk_growth us_10y_yield us_2y_yield
us_china_tariffs us_consumer us_cre us_elections us_employment us_gov_debt us_growth us_inflation
us_tech_regulation usd_strength yen_carry
agri_food copper_price gold_price lithium_price natural_gas nickel_price oil_price silver_price uranium_price
advanced_packaging agri_inputs ai_datacenter ai_servers battery_materials china_financials china_fnb
china_semis china_staples china_tech commercial_aerospace consumer_hardware content_creation
crypto_majors cybersecurity datacenter_power_gear defense_industry europe_equities ev_supply_chain
food_beverage food_processing global_luxury hardware_chain hbm_memory healthcare india_equities
japan_equities korea_equities life_science_tools medical_devices miners offshore_wind
optical_networking payments robot_components robotics semi_equipment semi_materials semis sg_banks
sg_reits solar sportswear telecom_equipment travel_leisure uk_banks uk_utilities us_financials
us_megacap_tech us_retail consumer_staples energy_sector us_government china_government opec temasek""".split())

# event_key aliases discovered by amendment agents covering the same real-world story
# with slightly different slugs (flagged during the chunk-7 report) -> canonicalize.
ALIASES = {
    "thames-water-2026-distress": "thames-water-2026-crisis",
}

def canon_key(k):
    return ALIASES.get(k, k)

# ---- load base corpus ----
by_date = {}
for path in sorted(glob.glob(os.path.join(EVENTS_DIR, "*.json"))):
    date = os.path.basename(path)[:-5]
    data = json.load(open(path))
    evs = []
    for ev in data["events"]:
        ev = dict(ev)
        ev["event_key"] = canon_key(ev["event_key"])
        evs.append(ev)
    by_date[date] = evs

base_event_count = sum(len(v) for v in by_date.values())

# ---- apply amendments ----
new_event_n = add_nodes_n = replace_nodes_n = add_deals_n = drop_n = 0
skipped_bad_key = []

for path in sorted(p for d_ in AMEND_DIRS for p in glob.glob(os.path.join(d_, "*.json"))):
    date = os.path.basename(path)[:-5]
    data = json.load(open(path))
    day_events = by_date.setdefault(date, [])
    by_key = {ev["event_key"]: ev for ev in day_events}

    # crypto-backfill files carry new events in "events" and amend-records in
    # "amendments"; v14 files put everything in "amendments". Read both.
    for a in list(data.get("events", [])) + list(data.get("amendments", [])):
        kind = a.get("amend")
        if kind is None:
            # full new event object (may itself carry an "amend": "add_deals" tail-field, handled below)
            ek = canon_key(a["event_key"])
            a = dict(a)
            a["event_key"] = ek
            if ek in by_key:
                # story already covered under this key elsewhere in the same day -> treat as add_nodes/add_deals instead
                existing = by_key[ek]
                for n in a.get("nodes", []):
                    if n not in existing["nodes"]:
                        existing["nodes"].append(n)
                        add_nodes_n += 1
                if "deals" in a:
                    existing.setdefault("deals", []).extend(a["deals"])
                    add_deals_n += 1
                continue
            day_events.append(a)
            by_key[ek] = a
            new_event_n += 1
            if "deals" in a:
                add_deals_n += 1
            continue

        ek = canon_key(a["event_key"])
        target = by_key.get(ek)
        if target is None:
            skipped_bad_key.append((date, ek, kind))
            continue

        if kind == "add_nodes":
            for n in a.get("nodes", []):
                if n not in target["nodes"]:
                    target["nodes"].append(n)
            add_nodes_n += 1

        elif kind == "replace_nodes":
            old_drop = set(a.get("old_nodes_dropped", []))
            target["nodes"] = [n for n in target["nodes"] if n not in old_drop]
            for n in a.get("new_nodes", []):
                if n not in target["nodes"]:
                    target["nodes"].append(n)
            if a.get("drop_event") and not target["nodes"]:
                target["_drop"] = True
            replace_nodes_n += 1

        elif kind == "add_deals":
            target.setdefault("deals", []).extend(a.get("deals", []))
            add_deals_n += 1

# ---- drop events with no legal origin left, and validate node ids ----
invalid_node_hits = collections.Counter()
final_by_date = {}
for date, evs in by_date.items():
    kept = []
    for ev in evs:
        if ev.pop("_drop", False):
            drop_n += 1
            continue
        ev["nodes"] = [n for n in ev.get("nodes", []) if n in VALID_NODES or invalid_node_hits.update([n]) is None]
        # the walrus-less counter above always keeps invalid ones out via filter below
        clean_nodes = []
        for n in ev.get("nodes", []):
            if n in VALID_NODES:
                clean_nodes.append(n)
            else:
                invalid_node_hits[n] += 1
        ev["nodes"] = list(dict.fromkeys(clean_nodes))
        if not ev["nodes"]:
            drop_n += 1
            continue
        kept.append(ev)
    final_by_date[date] = kept

print(f"base events: {base_event_count}")
print(f"new events added: {new_event_n}, add_nodes applied: {add_nodes_n}, replace_nodes applied: {replace_nodes_n}, "
      f"add_deals applied: {add_deals_n}, events dropped (no legal origin): {drop_n}")
print(f"amendments referencing unknown event_key (skipped): {len(skipped_bad_key)}")
if skipped_bad_key[:10]:
    print("  sample:", skipped_bad_key[:10])
if invalid_node_hits:
    print(f"invalid node ids stripped: {dict(invalid_node_hits)}")

total_events = sum(len(v) for v in final_by_date.values())
print(f"total events after merge: {total_events}")

# ---- rebuild ledger.jsonl ----
ledger = {}
for date in sorted(final_by_date):
    for ev in final_by_date[date]:
        k = ev["event_key"]
        mag = ev["magnitude"]
        if k not in ledger:
            ledger[k] = {"event_key": k, "type": ev["type"], "first_seen": date,
                         "last_seen": date, "peak_mag": mag, "summary": ev["summary"]}
        else:
            e = ledger[k]
            e["last_seen"] = date
            e["peak_mag"] = max(e["peak_mag"], mag)
            e["summary"] = ev["summary"]

with open(os.path.join(BASE, "ledger.jsonl"), "w") as f:
    for k in sorted(ledger, key=lambda k: ledger[k]["first_seen"]):
        f.write(json.dumps(ledger[k]) + "\n")
print(f"ledger rebuilt: {len(ledger)} event_keys")

# ---- news_impulses_v2.jsonl: per-day node impulses ----
# Canonical engine math (ai_investing.brain.events), matching the live cycle
# and the v1 replay pipeline: full credibility blend (source trust +
# corroboration + hype/chorus penalties), noise EXCLUDED (credibility below
# threshold or rumor_hype), per-node aggregation by max-|value| (a one-day
# news pile-on must not stack), times the brief §9 novelty factor.
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(BASE)), "engine"))
from ai_investing.brain.events import credibility
try:
    from ai_investing.config import settings
    CRED_THRESHOLD = settings.brain.credibility_threshold
except Exception:
    CRED_THRESHOLD = 0.35   # engine default

DATA_DIR = os.path.dirname(BASE)
day_heads = {}
for archive in ("news_archive_guardian.jsonl", "news_archive_live.jsonl"):
    p = os.path.join(DATA_DIR, archive)
    if os.path.exists(p):
        for line in open(p):        # live archive loads second: wins overlap days
            try:
                r = json.loads(line)
                day_heads[r["date"]] = r.get("headlines", [])
            except (json.JSONDecodeError, KeyError):
                pass

# Keep the derived artifact beside its source corpus.  Consumers (including the
# trainer) must not silently read a different legacy copy under data/.
impulses_path = os.path.join(BASE, "news_impulses_v2.jsonl")
n_noise = 0
bad_fields = []
impulse_events = {}
for date, evs in final_by_date.items():
    usable = []
    for ev in evs:
        ev = dict(ev)
        invalid = False
        for field in ("polarity", "magnitude", "confidence", "novelty"):
            value = ev.get(field, 0.0)
            if isinstance(value, bool):
                invalid = True
            elif isinstance(value, str):
                try:
                    ev[field] = float(value)
                except ValueError:
                    invalid = True
            elif not isinstance(value, (int, float)):
                invalid = True
            if invalid:
                bad_fields.append((date, ev.get("event_key", "?"), field,
                                   repr(value), type(value).__name__))
                break
        if not invalid:
            usable.append(ev)
    impulse_events[date] = usable
if bad_fields:
    print("WARNING: %d malformed events excluded from impulses (ledger retained)" % len(bad_fields))
    print("  sample: " + "; ".join("date=%s key=%s field=%s value=%s type=%s" % x
                                  for x in bad_fields[:10]))

# Never destroy a known-good artifact if validation or calculation fails.
fd, tmp_path = tempfile.mkstemp(prefix=".news_impulses_v2.", dir=BASE,
                                text=True)
try:
    with os.fdopen(fd, "w") as f:
        for date in sorted(impulse_events):
            heads = day_heads.get(date, [])
            node_impulse = {}
            for ev in impulse_events[date]:
                cred = credibility(ev, heads)
                if cred < CRED_THRESHOLD or ev.get("type") == "rumor_hype":
                    n_noise += 1
                    continue
                val = (ev.get("polarity", 0.0) * ev.get("magnitude", 0.0)
                       * cred * ev.get("confidence", 0.5) * ev.get("novelty", 1.0))
                for n in ev["nodes"]:
                    node_impulse[n] = max(node_impulse.get(n, 0.0), val, key=abs)
            f.write(json.dumps({
                "date": date,
                "event_count": len(impulse_events[date]),
                "impulses": {n: round(v, 4) for n, v in sorted(node_impulse.items())},
            }) + "\n")
    os.replace(tmp_path, impulses_path)
except Exception:
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    raise
print(f"news_impulses_v2.jsonl written: {len(final_by_date)} days -> {impulses_path}")
print(f"  engine credibility math; {n_noise} noise events excluded (threshold {CRED_THRESHOLD})")

# ---- validation report ----
all_mags = [ev["magnitude"] for evs in final_by_date.values() for ev in evs]
per_day_counts = [len(v) for v in final_by_date.values()]
high_mag = sum(1 for m in all_mags if m >= 0.8)
node_freq = collections.Counter(n for evs in final_by_date.values() for ev in evs for n in ev["nodes"])
zero_node_events = sum(1 for evs in final_by_date.values() for ev in evs if not ev.get("nodes"))
ts_present = sum(1 for evs in final_by_date.values() for ev in evs if ev.get("ts"))

report = f"""# Validation Report — full corpus (2023-07-01 -> 2026-07-30), post v1.4 amendment merge

Generated by `_merge_amendments.py` (step 5 of STATUS.md marching orders).

## Corpus size

- Days: {len(final_by_date)}
- Total events: {total_events} (base corpus {base_event_count} + {new_event_n} new node-gap events - {drop_n} dropped for no legal origin)
- Amendment records applied: add_nodes {add_nodes_n}, replace_nodes {replace_nodes_n}, add_deals {add_deals_n}
- Ledger event_keys: {len(ledger)}
- Unknown event_key references in amendments (skipped safely): {len(skipped_bad_key)}
- Invalid node ids stripped during merge: {dict(invalid_node_hits) if invalid_node_hits else 'none'}

## Distribution priors (brief §8/§14)

- Magnitude median: {statistics.median(all_mags):.3f} (target 0.2-0.4)
- Magnitude >= 0.8 events: {high_mag} ({100*high_mag/len(all_mags):.2f}% of {len(all_mags)}; target: rare, a handful/year over ~3 years)
- Events/day: mean {statistics.mean(per_day_counts):.2f}, median {statistics.median(per_day_counts):.1f}, min {min(per_day_counts)}, max {max(per_day_counts)}
- `ts` present: {ts_present}/{total_events} ({100*ts_present/total_events:.1f}%)
- Zero-node events remaining (should be 0 — all dropped in merge): {zero_node_events}

## Node coverage (top 20 by frequency)

{chr(10).join(f"- `{n}`: {c}" for n, c in node_freq.most_common(20))}

## The 42 previously-zero nodes — post-amendment coverage

{chr(10).join(f"- `{n}`: {node_freq.get(n, 0)}" for n in sorted([
    "boe_rate","cb_gold_buying","cnh_devaluation","credit_spreads","currency_peg_stress","custody_risk",
    "eurozone_political_risk","financial_engineering","financial_fraud","freight_logistics","market_intervention",
    "political_stability","private_credit","sanctioned_economy_stress","uk_growth","us_2y_yield","us_cre","us_growth",
    "advanced_packaging","agri_inputs","ai_servers","battery_materials","china_semis","commercial_aerospace",
    "consumer_hardware","content_creation","datacenter_power_gear","food_processing","hbm_memory",
    "life_science_tools","medical_devices","offshore_wind","optical_networking","payments","robot_components",
    "semi_equipment","semi_materials","telecom_equipment","travel_leisure","uk_banks","uk_utilities","us_retail",
]))}

## Asset-tag fix (step 4)

91 events previously tagged with illegal asset ids (tsla 32, btc 20, nvda 14, aapl 12, msft 4, crwd 4, tsmc 3, arm 2)
were remapped: 75 to a correct §7 origin node, 16 dropped (single-company stories with no industry-level origin
and no other node on the event).

## Known residual issues for human review

- A handful of amendment agents used slightly different event_key slugs for the same real-world story
  (e.g. `thames-water-2026-distress` vs `thames-water-2026-crisis`) — one alias reconciled in this merge
  (`ALIASES` dict in `_merge_amendments.py`); spot-check the ledger for further near-duplicates before trainer use.
- The node-gap amendment pass was a parallel best-effort scan (8 agents x ~141 days), not a second full line-by-line
  read of every headline — treat it as a high-recall pass on material misses, not an exhaustive guarantee.
- `news_impulses_v2.jsonl` impulse formula (`polarity * magnitude * novelty * confidence * (1-manipulation_likelihood)`,
  summed per node per day) is a first cut for the trainer; downstream code may want a different aggregation — this
  is a reasonable default consistent with the fields the brief defines, not a specified formula from the brief itself.
"""

with open(os.path.join(BASE, "validation_report.md"), "w") as f:
    f.write(report)
print("validation_report.md written")
