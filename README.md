# Invoice Pay Agent — Supplier Pay Agent for Mom-and-Pop Retail

An AI agent that turns a photo of a supplier invoice into a paid bill — and lives
inside a small working retail platform: invoice intelligence, a staff product
finder, and inventory/marketing dashboards, all on one data layer.

Built for the **PayPal AI Hackathon** (Devpost, submissions due Nov 12, 2026).

## The scored flow (Invoice Pay Agent)

1. A supplier invoice arrives (photo/scan).
2. AI vision extracts the line items.
3. Lines are matched against the store's item master (20,000+ SKUs in the
   production pilot) into a clean, reviewable bill with per-line match
   confidence.
4. A manager reviews and **approves** — a human is always in the loop.
5. On approval, the agent pays the supplier through **PayPal** (sandbox in this
   demo) and records the payment against the bill.

This workflow already runs in production at the pilot store (a real
independent liquor store in Effingham, Illinois) — the hackathon build adds
the PayPal payment leg.

## One PayPal rail, three loops — all built and working

Supplier Pay is the first loop on the rail. The same PayPal connection —
one token, one Payouts API, one approval doctrine, one ledger — also runs
the store's other two money-out jobs:

- **Ad Boosting (`/boost`).** Boosting means paying an ad platform to show
  a post to more people. The store's rule: only a pattern its **own post
  results have already proven** can be boosted — the in-app tracker lists
  each past post's reach, engagement, and store visits, and marks the ones
  that haven't proven themselves **not eligible** (the server enforces it,
  not just the label). The manager picks a proven pattern, sets a budget
  and a number of days, approves, and PayPal pays the ad platform. The
  boost, its budget, and its payout reference land in the same ledger.
- **Quick Runs (`/quick-runs`).** The errand loop for what distributors
  don't bring — cleaning supplies, bags, cups, receipt tape. The shift
  checklist flags the need, the agent builds the itemized cart at the
  store's usual spot-buy source, and PayPal pays on approval — or on the
  owner's standing **small-dollar rule**: runs at or under $25 are
  pre-approved and go on their own, with the notice after the fact.
  Delivery is tracked and the receipt files into the same books as an
  invoice, payout reference and all.

## The wider platform (same app)

- **Shelf Guide — staff product finder.** Name a product, get a dot on the
  store map plus the real shelf photo with the item circled. Proven in the
  pilot store on Oct 26, 2026: a full-store capture (157 photos + 15 videos)
  and 10 live finder tests, each verified against the physical shelves. The
  store's owners have cleared the layout/location material for this demo.
- **Trending × stock dashboard.** Sales velocity read against on-hand counts:
  trending + deep stock (push now), trending + nearly out (reorder flags),
  and the dead-stock money list — capital sitting still is a discovery
  problem, so the app surfaces it for promotion and findability.
- **Marketing queue.** Promotion drafts generated from the store's proven
  research-first ad workflow; a human approves before anything posts.

## A chain of custody for every dollar

Every invoice received, every count, every diagnosis, every claim, every
vendor credit, and every PayPal payout in this app is written to a single
append-only event ledger (`/ledger` in the app, `data/ledger.json` on
disk). Each event stores the SHA-256 hash of the event before it, and its
own hash is computed over that link plus its contents. Edit, delete, or
reorder any event later and the chain breaks at a specific, visible point —
the app's Verify button recomputes every hash and names the exact event
where the trail stops adding up.

That matters because these records settle arguments. When a supplier says a
case was delivered and the store says it never arrived, the question is
whose paperwork to trust. A hash-linked trail that neither side can quietly
rewrite after the fact is evidence, not just bookkeeping: the invoice, the
missing receiving record, the count, the diagnosis, the claim email, the
credit memo, and the reduced PayPal payout that recovered the money, all in
one ordered chain.

This is not a public blockchain and does not pretend to be one — there is
no token and no network, just the same tamper-evidence idea kept as one
honest local log. The design is deliberately chain-ready: because every
event is already hash-linked, the whole history (or just its head hash)
can later be anchored to a public chain without changing the event format.
That direction is worth being ready for — PayPal itself is building on
blockchain rails, including its PYUSD stablecoin — and a store's records
should be able to travel onto whatever rails its payments end up using.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
# open http://127.0.0.1:8000
```

Screens: `/` manager inbox → `/bill/<id>` review & pay · `/boost` ad boosting ·
`/quick-runs` the errand loop · `/variance` diagnoses ·
`/claims` credit claims · `/ledger` chain of custody · `/guide` Shelf Guide ·
`/dashboard` trending & marketing.

Try the scored flow: open `/extract`, download a **sample invoice photo**,
upload it back — the bill is extracted and matched line by line — then
**Add to inbox**, open the bill, and **Approve & Pay**.

## PayPal sandbox

Copy `.env.example` to `.env` and fill in your PayPal **sandbox** REST app
credentials (`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`). Without credentials
the app runs in a clearly-labeled **simulated** payment mode so the full flow
can be reviewed; with them, approval triggers a real sandbox payout.
Credentials are read from the environment only — never commit them.

## Data notes

- The pay flow uses **fictional** suppliers, invoices, and a mini item master
  (`data/`). No real store financial data (costs, margins, vendor terms) is in
  this repo.
- The Shelf Guide module uses the pilot store's **real** layout and product
  locations, with the owners' permission (layout/location material only).

## Roadmap to Nov 12

- [x] Skeleton: three screens, sample data, simulated/sandbox payment path
- [x] Live extraction + matching on uploaded invoice photos — the demo
  vision step (`app/vision.py`) is fixture-backed: sample invoice photos
  are recognized by content/perceptual hash and read as their verified
  ground-truth text, so the flow runs with no extra keys. Production
  swaps in an OCR/vision model behind the same interface.
- [x] Hosted demo deployment — live at https://invoice-pay-agent.onrender.com
- [x] All three PayPal rails built: Supplier Pay, Ad Boosting, Quick Runs
- [ ] Demo video (<3 min) + Devpost submission (target: Nov 11)

## Why one rail matters

A small store's money leaves through more doors than supplier invoices —
it pays for reach and it pays for the run to the store. Running all three
on the one PayPal connection the store already trusts means every dollar
out gets the same treatment: a human-approved (or owner-rule-approved)
decision, a real payout with a reference, and a line in the same
hash-linked ledger. Nothing moves off the books, and nothing moves
without a yes the owner set the terms for.

## License

MIT — see `LICENSE`.
