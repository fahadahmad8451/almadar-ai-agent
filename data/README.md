# data/ — synthetic seed data (never real data)

- `scripts/seed.py` loads the seed data into PostgreSQL (database
  `almadar_agent`). It is the single source of seed data: Saudi suppliers,
  invoices with 15% VAT, CRM customers/leads/deals, expense claims,
  demo users, the 4 core workflows and the 3 locked scheduled jobs.
- `data/exports/` (created at runtime, gitignored) holds report
  exports produced by approved runs.
- `data/uploads/` (created at runtime, gitignored) holds attached
  invoice PDFs awaiting the OCR workflow.

Nothing in this folder is real customer, supplier, or financial data.
