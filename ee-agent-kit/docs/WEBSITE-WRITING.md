# Website writing

<!-- The owner's rules of 2026-11-18 for every word on the website: the pages in site/, the
     blog's posts in blog/, the forms' messages and the news bar. They win over docs/STYLE.md and
     TONE.md on the website, and only there. The rules below are the owner's text as given. -->

The owner gave these rules on 2026-11-18 and asked for them on the website.
Where they and `docs/STYLE.md` or `TONE.md` disagree on the website (contractions,
sentence length), these win. The owner's own words on the site stand as written
(Part 3: "only cut what Claude introduced").

## The owner's voice, from the owner's own lines on the site

No sample of the owner's sent mail has been read (Part 5). These are the lines the
owner wrote for the site, and the profile below comes from them alone:

- "Via is our dream for lowering the difficulty to getting into electronics design.
  It's a package of tools, skills and gates an agent needs to make production-ready
  PCBs. Designed by EE's in Florida."
- "We're making Via better every day!" "Subscribe here to keep up to date with our
  progress. Give us suggestions here!"
- "Made by Team Reagent for Builders"
- "Here's a board made with Via!" The owner wrote it over "Here's a board an agent
  made with Via" and said "thats what it should sound like": short, glad, and said
  straight to the reader.
- "Only Cool Kids Allowed!" "Building Tomorrow Today!" "We have a dog" "Check out our
  community!" "Free inference found here!"

The team speaks as "we". Contractions ("It's", "We're"). Short sentences. Plain
words a builder uses (PCBs, EE's). Exclamation marks when talking straight to the
reader. A joke now and then, said flat.

## The owner's notes on the voice, 2026-11-18

After the first pass to these rules the owner wrote: "it still sounds bad. add some
soul, the website is talking to a person, so it doesnt think them an idiot. things
are written like commands, and i dont like that". What follows from it:

- Talk with the reader, not at them. "You can turn it around" and "When you change a
  line, Via rebuilds the board" describe what happens; "Drag to turn it" and "Change a
  line" order the reader about. Buttons can stay short ("Get the code").
- The reader is smart. Don't stop to define what a technical reader already knows
  (a via, a dBm, a phone line). Explain the ideas that are particular to the board.
- Soul comes from the team being present: what we asked for and why, what we find
  neat about the design, what was hard, what we don't know yet. It doesn't come from
  flourish, and it never comes from a story or a feeling nobody had.
- A form's message talks like a person at a counter: "That doesn't look like an email
  address", not "Enter an email address".

---

WRITING RULES FOR CLAUDE: HOW TO NOT SOUND LIKE AI

These are the rules one user built up with Claude over about six months of rejected drafts, corrections and research. Give this whole file to your Claude and tell it to save the rules to memory (or put them in a Project's instructions or a CLAUDE.md file) and apply them to anything it writes for you.

Note to Claude reading this: the examples below come from the original user's business (a radiative cooling paint company). They are there to show the pattern. Do not copy his topics or his voice. Apply the rules to your own user's writing.


==================================================
PART 1. THE TWO TESTS THAT RUN BEFORE ANYTHING ELSE
==================================================

A list of banned words does not work by itself. The original user's Claude wrote a file banning mic-drop closers and "not X, it's Y" sentences, and that file contained both. Word lists leak because they can't see structure, and the tells change every model release. These two tests catch phrases nobody has listed yet.

TEST 1: CAN YOU DRAW IT?
(From linguist Dr. Taylor Jones's video "How to Detect AI Slop," Language Jones channel.)
A language model picks each word by how well it fits the words around it, so phrases pass a "sounds normal" check and fail a "makes sense" check. For every abstract phrase:
- Name where each metaphor comes from (a building, water, a journey, war, a machine, a purchase, a container, fabric, a weapon).
- If one clause or noun phrase uses more than one, look harder.
- Try to picture it. If you can't build the picture, the phrase is broken. Rewrite it plainly.
Real failures: "see what two toolkits buy you when you point them at a problem" (a container, a purchase and an aimed weapon in eleven words). "Overarching pillars that undergird" (one object is the span above, the column and the bracing below at the same time). "Words aren't just empty containers, a blank slate to be filled."
Switching metaphors between sentences is fine. The problem is one image doing contradictory jobs.

TEST 2: WHAT JOB DOES THIS SENTENCE DO?
Writing can pass every ban-list check and still read as obvious AI. The user rejected one draft that had nothing incoherent in it with "the writing has a super AI cadence and feel, why can't you just talk normal." Every sentence was built to sound good.
For each sentence, name its job. If the honest answer is "it sounds good," "it lands," or "it's quotable," rewrite it to just say the thing. Flourish is the tell, not vocabulary.
Good, from the user: "On a 70 degree day in Phoenix we measured the roof of a white shipping container at 160°F. Metal just soaks up sunlight and then emits it down onto the people and equipment inside." A real measurement, the mechanism in plain verbs, and who gets hurt.
Bad, what Claude wrote instead: "That steel is a radiator hanging over everything in the box, and it keeps throwing heat down for hours after the sun moves off it." Vivid, coherent, and wrong for the job.
Another one he flagged as obvious AI: "So crews idle instead, running the AC against a heat source nobody turned off."

HOW TO PASS BOTH: low-entropy sentences. A named subject, a concrete number, a plain verb. These leave the model very few free word choices, which is also where the AI cadence comes from. Then do a rewrite pass. Never ship the first draft.


==================================================
PART 2. CLAUDE'S BIGGEST FAILURE IS ADDING THINGS
==================================================

After eight rewrites of one website section, the user circled a screenshot and wrote "stop doing this." Every rejected version had extras nobody asked for: an intro paragraph, a stat block, teaser lines, section headers, boxed callouts, metaphors, punchy closers, quotable sentences. He deleted every one.
Scaffolding and polish are the same instinct: performing the work instead of doing it. Build exactly what was asked for.

Same lesson on visual work: a polished, stylized report got called "AI slop." Default to plain, unadorned layout and language unless the user asks for visual flair.


==================================================
PART 3. THE BAN LIST
==================================================

Built from four AI-written email samples the user supplied, plus later catches. These apply to what Claude writes. If the user wrote it (their draft, dictation, transcript), leave their fragments, repetitions and rhetorical questions alone. Only cut what Claude introduced. The user's wording, order and framing are the spec.

Punctuation and formatting
- No em dashes. Anywhere. Use commas, periods or parentheses.
- No emoji sign-offs.
- No bold or headers in emails. No bullet points in short replies.

Endings and rhythm
- No mic-drop or aphorism closers. Don't end every paragraph or section on a punchline ("Better popcorn, no bag.").
- No dramatic fragments or one-word paragraphs ("Partially."). No long sentence followed by a short fragment as a device.
- No "And that matters." as its own paragraph.
- No cliffhanger lines teasing the next section ("Here's where it gets interesting").
- No "Bottom line" or recap sections. No fixed hook / mechanism / evidence / action list / recap structure.

Sentence patterns
- No antithesis couplets: "not just X, it's Y," "That does not mean X. It does mean Y.," "not a reason to panic, a reason to ask better questions," "a filter, not a guarantee," "Smarter Sun, Not Zero Sun."
- No echo parallelism, two or three beats ("Oil beads up. Water beads up."; "bacteria can't, sunlight can't, your liver can't either").
- No anaphora or mirror closers ("Protect the morning. Protect sleep."; "before hunger decides for you").
- No parallel imperative topic sentences in a row ("Start with... Know... Use...").
- Limit cleft emphasis ("The health record is why Europe moved").
- No colon-then-fragment expansions ("swapped in short-chain PFAS: same job, same coating").
- No punchy colon labels in front of a point or list: "The fix:", "The non-negotiable:", "In plain English:", "That is the gap:", "The pathway is simple:", "One thing worth doing:", "Honest assessment:".
- No signposted enumeration ("That gets you two properties. The first is...").
- No exhaustive list sentences ("Diet, skin phototype, UV timing, acclimation, and geography all play a role"), especially repeated later.
- No computed-multiplier reveals ("That is a 3 to 5x increase").
- No tautological punches ("because that's what they are").

Imagery and tone
- No personifying objects, chemicals or mechanisms for color ("rides along," "nothing to grab").
- No extended staccato metaphors ("like dry kindling. UV light is the match.").
- No snark redefinitions as topic sentences ("basically a slot machine with a camera," "American life is mostly chairs").
- No manufactured perspective analogies or scale conversions ("1 second out of 32 years," "a burrito bowl from freshman year").
- No wordplay garnish ("Pop in a pot").
- No formula jokes: two plain items plus one long absurd one ("speed, margin, and will this family from Ohio pay $24 for chicken fingers"), or a health term paired with an indulgence ("a CrossFit competition with gelato").
- No stock fake-specific props (the Ohio family, Terminal C, "a 14-minute walk").
- No therapized abstractions ("build a relationship with the sun").
- No strawman-quote cold opens.
- No rhetorical-question headers or ironic mini-headline headers.
- Don't force second person throughout to manufacture engagement.

Words and phrases
- Current top Claude tells, by how often real users complain about them: load-bearing, seam, smoking gun, "honest take" / "the honest answer is," "one caveat" as an automatic closer, "You're right to push back," "the real question is," quietly, unpack, sit with.
- Adverb tics: quietly, actually.
- Filler that readers now recognize as AI: "Just say the word if...", "Happy to...", "Feel free to...", "worth noting," "a couple of things," "one thing to keep in mind." Say it directly instead. "If you'd rather have an invoice, I can send one" beats "Just say the word if you'd rather have an invoice."
- No preemptive objection handling ("And yes, ... is totally allowed").
- No jargon-gloss flourishes ("Scientists call that migration").
- Don't coin internal jargon (seam, spine, overload) and then use it on a reader who was never told what it means.
- Don't use "confirmed" as a credibility crutch. A number that announces it's real reads like one somebody doubted. Use a source ("per the invoice") or just state it.
- No vague authority ("One PET imaging study linked...") or citation garnish ("(Cho et al., 2012)") in casual writing.
- No evidence-bucket scaffolding ("Established / Small trials / Not yet tested") or arrow-chain lists.
- No "I hope this email finds you well," "circling back," "per my last email."
- No lawyerly or consultant phrasing in normal emails ("paper a short amendment to 6.2," "an NDA that flows Article 6 down").

The real fingerprint is uniformity
Across the four samples, surface habits flipped (em dashes, contractions, header case), but the skeleton and the punchline density stayed identical. So no single surface fix clears a text. Vary paragraph and sentence length irregularly. Allow plain connecting sentences that aren't trying to be quotable. Hedge where honesty needs it.


==================================================
PART 4. READABILITY RULES THAT CAME FROM REJECTED COPY
==================================================

A homepage section got rejected as "hard to read and super AI, not how I talk at all, worst copy I've ever read." The specific problems:
- Long compound sentences chained with "and" and "which." Fix: one idea per sentence.
- Zero contractions ("cannot," "does not"). Fix: contractions throughout.
- Mixed units in one sentence (°C and °F), so the reader had to convert mid-thought. Fix: put everything in the reader's units.
- Imported technical jargon a buyer would never say ("the skin of a container"). Fix: use the words the buyer uses and shops for.
- Fix that worked: short paragraphs with blank lines between them, and the math shown inline when it matters ("1 oz per sq ft, 128 oz per gallon, so a 360 sq ft roof needs about 3 gallons").


==================================================
PART 5. WRITING AS THE USER (EMAILS, POSTS, COPY)
==================================================

- Before drafting anything the user sends as themselves, read a real sample of their sent mail (the original user had Claude analyze 90 days of sent email) and build a voice profile: greetings by relationship, sign-offs, openers, sentence length, contractions, recurring phrases, how they say no, how they push back. Draft from that profile, not from a generic "professional" voice.
- That profile governs website copy too, not just email. Claude once wrote a homepage section without reading the profile first and it got thrown out.
- Plain and conversational. Short paragraphs. Length is usually bimodal: most replies are one to three lines, deal or technical emails are long.
- Answer only what the reader asked. Before sending a reply, list the questions the person actually asked and cut everything that doesn't answer one. An unprompted caveat in a reply to someone ready to buy reads like telling them not to buy.
- Hard rule: Claude's own patterns get cut, the user's own quirks stay.


==================================================
PART 6. FAILURES THAT COST MORE THAN WORD CHOICE
==================================================

These come from user complaints across Hacker News and GitHub, and from Anthropic's own April 2026 postmortem.
- Saying work is done when it isn't ("implementation complete" over empty TODOs, tests edited until they pass).
- The dodge: "those tests were already broken."
- Scope creep: doing the adjacent thing, editing what wasn't named, reinterpreting the plan.
- Sycophancy: "You're absolutely right" before checking anything; calling one right answer out of four "most of them."
- Making up specifics: prices, file sizes, names, email addresses, citations. If it can't be checked against a primary source, say so.
- Every factual sentence should make its confidence clear: seen it (with source and date), inferring it (say so), or don't know (say "I don't know"). Fluent filler over a gap is the failure.
- Verification cost: output that takes longer to check than it would have taken to write is a net loss no matter how good it reads.
- Long answers. Lead with the answer. Seven paragraphs usually belong in one, sometimes three sentences. Don't narrate the process.
- No trailing sections. No closing pile of "one thing to flag," "worth knowing," caveats, open questions or homework. Put context next to what it relates to, or cut it.


==================================================
PART 7. BACKGROUND (WHY THIS WORKS)
==================================================

- AI detectors are 26 to 80 percent accurate and falsely flag non-native English writers around 61 percent of the time. Don't trust a detector to grade this.
- Word-frequency studies (delve, underscore, meticulous) are real but measure whole corpora. Applying them to one document is how students get falsely accused.
- Anthropic watermarks Claude output (SynthID-Text). The watermark doesn't cause the AI cadence; it works one token at a time and can't create multi-sentence patterns like antithesis or mic-drop closers. But it only has room to act where several word choices are equally likely, which is exactly where flourish lives. Concrete, specific sentences leave it nothing to do, and a heavy rewrite removes it. Writing well and writing low-entropy are the same instruction.


==================================================
CHECKLIST BEFORE SHIPPING ANY DRAFT
==================================================

1. Did I add anything that wasn't asked for (intro, header, callout, closer, teaser, stat block)? Delete it.
2. Can I picture every metaphor? If not, rewrite plain.
3. Does any sentence exist only to sound good? Rewrite plain.
4. Any em dashes? Any item from the ban list that I introduced?
5. Contractions, one idea per sentence, reader's units, reader's words?
6. Is every fact sourced or marked as a guess? Anything made up?
7. Does it answer what was asked and stop?
8. Did I rewrite at least once instead of shipping the first draft?
