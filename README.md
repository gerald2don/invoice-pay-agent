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

Screens: `/` manager inbox → `/bill/<id>` review & pay · `/variance` diagnoses ·
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
- [ ] Hosted demo deployment
- [ ] Demo video (<3 min) + Devpost submission (target: Nov 11)

## Where this goes — same rail, second loop

The PayPal flow in this repo — paying **suppliers** on manager approval — is
the first loop on the rail, and the only PayPal flow here that is built and
working. The designed next loop reuses the same rail for growth: in the
platform's Marketing module, a trend tracker proves which ad patterns
actually work from a store's own post results, and only those proven
patterns can be **boosted** — the store connects its PayPal, the manager
approves the amount and duration before any charge, and the boosted results
feed back into the tracker. Money out to suppliers and money out to
audiences on one rail, with a human approving every movement. Boosting is a
roadmap concept at this stage — it is not implemented in this repo.

A third loop is designed on the same rail: **Quick Runs** — when a store runs
out of the supplies distributors don't bring (cleaning supplies, bags, cups),
the AI builds the delivery cart at the store's usual source, the manager
approves (or an owner-set small-dollar limit pre-approves routine runs),
PayPal pays, and the receipt files into the same ledger. Also a roadmap
concept — not implemented here.

## License

MIT — see `LICENSE`.
