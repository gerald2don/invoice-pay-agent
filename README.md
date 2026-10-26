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

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
# open http://127.0.0.1:8000
```

Screens: `/` manager inbox → `/bill/<id>` review & pay · `/guide` Shelf Guide ·
`/dashboard` trending & marketing.

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
- [ ] Live extraction + matching on uploaded invoice photos
- [ ] Hosted demo deployment
- [ ] Demo video (<3 min) + Devpost submission (target: Nov 11)

## License

MIT — see `LICENSE`.
