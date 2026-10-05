# Provenance of the source documents

Every source in the vault is a public US-government record. Nothing here was scraped from a site
whose terms forbid it.

| Document | In this repository | Where it comes from | SHA-256 |
|---|---|---|---|
| FAA Advisory Circular AC 43.13-1B, Change 1 (2001-09-27), 646 pages | `data/raw/AC_43.13-1B_w-chg1.pdf` | faa.gov, Advisory Circulars library | `8dc99dd41334381b287ae02d03dc29928d9eacb1035b67aa24c5a0525324ee73` |
| FAA Airworthiness Directives, 683 Federal Register documents | `data/raw/ads/*.txt` | federalregister.gov full-text endpoint; the URL of each document is in `data/raw/ads/index.json` | per-file, recomputable |
| MIL-HDBK-5J, *Metallic Materials and Elements for Aerospace Vehicle Structures* (2003), 1,733 pages, Distribution Statement A | **not included** (67 MB) | DLA ASSIST Quick Search, document ident 53876: https://quicksearch.dla.mil/qsDocDetails.aspx?ident_number=53876 | `7e0b2926cc7c49dab379354a50859a34ef834489a3c8ed45f8c6ad87bd18c60d` |

The facts extracted from the handbook are in `data/facts/lot5-manual` and `data/facts/lot6-manual`,
each with its page and excerpt, so they can be checked against the PDF after downloading it. No test
needs the handbook. `tests/test_provenance.py` reads the AC PDF to verify, word for word, the four
excerpts that give the rules their numbers.

Page counts were measured with
`uv run --with pymupdf python -c "import pymupdf; print(pymupdf.open('data/raw/MIL-HDBK-5J.pdf').page_count)"`
and are recorded in `data/raw/vault.json`.
