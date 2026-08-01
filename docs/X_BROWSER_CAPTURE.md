# X (Twitter) browser-capture protocol — for an AI operator with Claude-in-Chrome

*Version 1.0, 2026-08-01. Purpose: harvest crypto news posts from the user's
followed X accounts using their logged-in Chrome session (claude-in-chrome
tools) — no API, no cost. Output feeds `data/news_archive_x.jsonl` and, for
historical days, the crypto-backfill digestion campaign
(`data/digest_v2/crypto_backfill/`). Proven workflow: three capture sessions
on 2026-07-31 collected 33 posts this way.*

## 0. Hard rules (read first)

1. **ONE Claude-in-Chrome session, ever.** Never run capture from two
   AI sessions/agents concurrently, and never parallelize capture across
   subagents — X throttles (and may challenge) accounts showing
   multi-headed browsing. Before starting: call `tabs_context_mcp`, close
   any stray MCP tabs from previous sessions, and if another session
   appears to be mid-capture (e.g. `news_archive_x.jsonl` modified within
   the last 15 minutes), do not start — report and wait. A real user is
   one person with one browser; be that.
2. **READ-ONLY.** Never post, reply, like, repost, follow, unfollow, or
   change any account setting. Never enter credentials, phone numbers, or
   2FA codes into anything — if X shows a verification/phone/password
   modal, dismiss it (back arrow / Esc) and continue; if it blocks
   browsing, stop the session and report.
3. **One tab, human pacing.** Single MCP tab for the whole session.
   Waits of 2-3s after navigation, ~0.8s between scroll steps. If X shows
   a rate-limit or unusual-activity interstitial, END the session — do not
   push through.
4. **NEVER capture a tweet twice** (the dedup contract, §3).
5. **X hijacks bare keystrokes as shortcuts** (`n` opens the composer,
   others navigate). Never use the `type` action unless a screenshot/zoom
   confirms a focused text input (blue border). This protocol needs no
   typing at all — navigate by URL only.
6. Ads (`Ad` label), pinned promos, and "Who to follow" blocks are not
   posts — the harvester below excludes them automatically because they
   lack a `/status/` time link or carry no fresh timestamp.

## 1. What to capture

Profiles to visit (URL = `https://x.com/<handle>`), in priority order:

| Tier | Handles | Trust prior (already in events.py) |
|---|---|---|
| Data/flows | FarsideUK (0.8), glassnode (0.7) | numbers are the payload — capture full text |
| News | WuBlockchain (0.6), TheBlockCo (0.65), Blockworks (0.6), MessariCrypto (0.6), coinbureau (0.5) | |
| Regulatory/fraud | EleanorTerrett (0.7), zachxbt (0.7) | |
| Fast wire | WatcherGuru (0.35) | high volume, capture all, digester discounts |
| Primary voices | brian_armstrong, cz_binance | statements are facts, framing is not |
| Sentiment gauges | scottmelker, RaoulGMI, Rager, MacroCRG, benjamincowen, PlanB + any other accounts the user follows (check /home Following tab) | generic 0.25 floor |

Also capture the chronological **Following feed** (`x.com/home`, Following
tab) once per session — it catches accounts not listed above that the user
has since followed.

## 2. The harvester — DRAIN each profile before moving on

Work one profile at a time: enter it, scroll patiently until the timeline
stops yielding new posts (or the cutoff is reached), capture everything,
and only then move to the next profile. Depth beats breadth: a
half-scrolled profile wastes the visit.

After navigating and waiting ~3s, run this with `javascript_tool`
(REPL semantics, top-level await works). It scrolls in SMALL steps with
human pacing — X's virtualized list only mounts posts that render, so
slow-and-small collects far more than fast-and-big — and it stops itself
when the feed runs dry (8 consecutive steps with nothing new) or after
~150 steps (~4 min), whichever comes first:

```js
window.__cap=new Map();
const cutoff=Date.now()-N_DAYS*864e5;   // set N_DAYS per §4
const h=()=>{document.querySelectorAll('article').forEach(a=>{try{
  const tl=a.querySelector('a[href*="/status/"] time'); if(!tl)return;
  const u=tl.closest('a').getAttribute('href');
  const t=tl.getAttribute('datetime');
  if(new Date(t).getTime()<cutoff)return;
  const txt=a.querySelector('[data-testid="tweetText"]');
  if(!window.__cap.has(u))window.__cap.set(u,{u,t,
    x:txt?txt.innerText.replace(/\n+/g,' ').slice(0,400):''});
}catch(e){}})};
h();
let dry=0;
for(let i=0;i<150&&dry<8;i++){
  const before=window.__cap.size;
  window.scrollBy(0,900);                      // small steps: let posts mount
  await new Promise(r=>setTimeout(r,1300));
  h();
  dry = window.__cap.size>before ? 0 : dry+1;  // reset on any new post
}
'collected '+window.__cap.size+' (drained: '+(dry>=8)+')'
```

If it returns `drained: false` (hit the 150-step cap with posts still
coming), the profile has more history than one visit should take — note
where you stopped and continue it NEXT session rather than looping again
now (rule 3: don't hammer).

Then read results in slices (tool output truncates near ~1,000 chars):

```js
JSON.stringify([...window.__cap.values()].slice(0,4))   // then 4..8, 8..12, ...
```

## 3. Dedup contract — do not re-capture what we already have

Before writing anything, load the set of already-captured status IDs:

```bash
python3 - <<'EOF'
import json
seen = set()
for line in open("data/news_archive_x.jsonl"):
    for h in json.loads(line).get("headlines", []):
        u = h.get("url", "")
        if "/status/" in u:
            seen.add(u.rsplit("/", 1)[-1])
print(len(seen), "already captured")
EOF
```

Discard every harvested post whose status ID is in that set. The status ID
is the number after `/status/` in the harvested `u` field.

## 4. Session cadence — few profiles, fully drained

- **Daily session** (primary): N_DAYS=3. The Following feed first, then
  drain the News/Data/Regulatory-tier profiles one by one (the drain loop
  self-terminates fast on a 3-day cutoff — a quiet profile finishes in
  under a minute). ~20-30 min, expect 40-100 new posts.
- **Depth session** (backfill): N_DAYS=60-90 on 2-3 profiles ONLY, each
  drained to the dry-stop or step cap; resume unfinished profiles next
  session. Rotate through the roster across days until every profile's
  reachable history is captured. Older posts land in already-digested
  days — that is fine; they flow to the amendment campaign via
  staging (§6).
- Between profiles: a 5-10s pause (navigate, wait, breathe) — one
  continuous drain per profile per session is the intended rhythm, many
  short revisits to the same profile in one session is what rule 3
  forbids.

## 5. Writing the archive (exact format)

Convert each new post to a headline record and append **day-records
grouped by the post's UTC date** to `data/news_archive_x.jsonl`:

- Exact timestamp: the harvester's `t` is an ISO datetime — use it
  directly. (Equivalently, status IDs are snowflakes:
  `ts_ms = (id >> 22) + 1288834974657`.)
- `title`: a clean one-line restatement of the post's news content
  (strip "JUST IN:", emojis, cashtag noise). `summary`: remaining detail.
  Pure-promo posts (subscribe links, giveaways) are skipped, but posts
  that are only sentiment ARE kept — labeled as gauges in the summary.
- Record shape (one line per date):

```json
{"date": "2026-08-01", "ts": "<capture time ISO>",
 "capture": "browser session, <which profiles>",
 "headlines": [{"title": "...", "summary": "...",
   "published": "Fri, 01 Aug 2026 09:15:00 GMT",
   "ts": "2026-08-01T09:15:00+00:00",
   "source": "x.com/<handle>",
   "url": "https://x.com/<handle>/status/<id>"}]}
```

`source` must be `x.com/<handle>` verbatim — per-handle trust priors in
`engine/ai_investing/brain/events.py` key on it.

## 6. After capture

- Posts dated TODAY: nothing more to do — the daily digestion session
  reads `news_archive_x.jsonl` alongside the RSS live archive.
- Posts dated on ALREADY-DIGESTED days: run
  `python3 data/digest_v2/crypto_backfill/_stage.py` — it folds the X
  archive into the crypto-backfill staging, where the Sonnet amendment
  campaign picks them up under its anti-double-count rules.

## 7. Incident log (learn from these)

- 2026-07-31: typing into an unfocused page triggered X keyboard
  shortcuts, opened a phone-number modal (dismissed, nothing entered).
  Rule 5 exists because of this.
- Impostor accounts are everywhere in search (fake ZachXBT/WatcherGuru
  rows). This protocol navigates by exact profile URL, never by search.
- A second MCP tab once navigated on its own through settings pages —
  close stray tabs at session start; work in exactly one.
