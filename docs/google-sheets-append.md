# Google Sheets append adapter contract

`scripts/sheet_rows.py` builds typed rows and append requests; it does not authenticate or call Google APIs. A caller may pass `spreadsheet_url` in `review.json`; the public code contains no spreadsheet ID or OAuth credentials.

Before writing, the external adapter must read workbook metadata and bounded ranges, verify tab names and headers against `HEADERS`, compute empty tail rows, detect an existing run ID and COMMIT, and verify formatting and cell validation. Append all rows in one logical batch with the COMMIT last, then read back every appended range. Never overwrite history. Resolve ambiguous write results by reading the run ID before retrying. Sheets does not provide a database uniqueness lock, so use a single writer.

Do not record target weights as actual holdings or fills. Unknown account positions and cooldown state must remain explicitly unverified.
