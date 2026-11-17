# Product kinds

A product kind lists the requirements that free documents state for a kind of product, each with its
document and clause, in our own short words. `workcenter standards <project>` reads the kind that the
project's `product.json` names and says what holds each requirement: a gate (the layout pack that judges
it, named in `board-rules.json` and run on the project's board with 0 fail and 0 not judged), a test
(requirements of the project's verification package that read PASS), or nothing. `left_out` names each
clause of a read document that the kind does not list, with the reason; the report prints them.

A kind holds no text of a document and no number of a paid standard. It names the paid standards a test
laboratory uses (`laboratory`) and the documents that could not be had (`not_had`), with the reason.

## vaping-device-lithium-cell

A vaping device with a rechargeable lithium-ion cell, a digital controller and a USB port, sold in the
United States. Read 2026-11-17, with no second reader yet.

| Document | Revision | Clauses |
|---|---|---|
| 47 CFR Part 15, Subpart B (eCFR) | as of 2026-11-01 | 15.101(a), 15.105(b), 15.107(a) and (d), 15.109(a) |
| 49 CFR 173.185 (eCFR) | as of 2026-11-01 | (a)(1), (a)(2), (a)(3), (a)(4)(i) to (iii), (a)(5); (b)(1), (b)(2), (b)(4), (b)(7); (c); (e). Left out, each with its reason in `left_out`: (a)(1)(i) and (ii), (b)(3), (b)(5), (b)(6), (d), (f), (g), (h) |
| TI SLVA680A | Rev. A, April 2022 | section 1 page 2, section 2.1 page 4, section 2.3 page 6 |
| TI SZZA009 | November 1999 | section 2.1.1 page 4, section 2.2.4 page 10 |

Not had: Directive 2014/40/EU (Article 20) and Directive 2014/30/EU (Annex I). eur-lex.europa.eu
answered HTTP 202 with no body to the client `ee-workcenter/1.0` on 2026-11-17. The kind says nothing of
the EU market until they are read.

A test laboratory uses UL 8139, IEC 62133-2, ANSI C63.4-2014 (named by 47 CFR 15.31(a)(4)),
IEC 61000-4-2, and the UN Manual of Tests and Criteria, sub-section 38.3.
