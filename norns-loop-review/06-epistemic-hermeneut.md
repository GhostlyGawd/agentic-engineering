# Hermeneutic Review: norns-loop

## 1. The Charter as Constitutional Document

The first thing to notice about CHARTER.md is that it does not read like a technical spec. It reads like a constitution. Section headings are pinned, hard, fixed, immutable. The vocabulary is borrowed wholesale from political-legal genres: "Goal (pinned)", "Hard constraints", "Roles (the triad — fixed, not fungible)", "veto", "halt", "violation". The closest secular analogue is a board of directors' resolution; the closest sacred analogue is a covenant.

This matters because the document is performing an act its content cannot quite name: it is binding *future agents to past agents*. The sha256 in `.charter-lock` (`6dc7eaa6...`) is the closest thing this codebase has to a signature. Every session that boots reads it and is, in effect, asked to consent.

The verb tense gives this away. "Build a Creatures-style artificial life simulation" (§1) is bare imperative. No subject. Who is being commanded? Not "you, the developer" — there is no developer in the singular. Not "we, the team" — the team will be ephemeral, dying and respawning at every 200k-token tripwire. The imperative addresses *whoever happens to be reading*. It is the charter speaking, not its author.

The word "fungible" in §3 ("the triad — fixed, not fungible") is striking. "Fungible" is a finance/commodity term: gold bars are fungible, paintings are not. To say PM/Builder/Critic are "not fungible" is to insist they are not interchangeable instances of "a Claude session". They are *roles* in the dramaturgical sense — masks that constrain who may speak about what. The same model weights underlie all three. The charter insists they remain distinct anyway. This is the document's deepest theological claim: that role is constitutive, not decorative.

## 2. Named and Unnamed: The Authority Cascade

The triad is named. So are specific subagent dispatchers — `oh-my-claudecode:architect`, `oh-my-claudecode:writer`. So is the orchestrator (the watchdog). So is the human, obliquely: "the other two sessions cover" (§7) implies a community of peers; "halts and writes CHARTER_VIOLATION.md" (§6) implies an audience that will read the violation.

What is *not* named in the charter is illuminating:

- **The OMC subagents themselves** beyond the two examples. §4 mentions "OMC subagents for all heavy work (planning, code-writing, review, eval running, debugging)" but does not enumerate them. They are workforce, not citizenry. The triad has names; the workforce has functions.
- **The human owner.** The charter never says "Rhen" or "the operator" or "the human". The closest the document comes is the bare path `D:\tmp\omc-test-a` in §2 — a Windows path that anchors the constitution in a single machine, a single user account, a single OS install. The covenant is sworn on a temp directory.
- **Anthropic, Claude, the model.** The substrate that makes this run at all is never acknowledged in CHARTER.md. (It appears only in incidental retro trailers: `Co-Authored-By: Claude Opus 4.7 (1M context)`.)

This is the authority cascade made visible by what it elides: a real human, paying a real company, instantiating three roles that govern themselves by reference to a hash that they cannot rewrite. The charter encodes a *managed autonomy* — autonomy bounded by something the autonomous agents cannot reach.

## 3. "The triad cannot be replaced or merged" — Addressee and Anxiety

§3's closing line — "New supporting roles may be added by the PM with Critic approval, but the triad cannot be replaced or merged" — has a curious structure. Who is being told?

It cannot be the PM. The PM already operates inside the triad and would not be the party *replacing* it. It cannot quite be a future maintainer either, because a maintainer would simply rewrite CHARTER.md (which is why it is hash-locked).

The addressee is the loop itself, in its capacity to drift. The sentence anticipates the most plausible failure mode of long-running autonomous systems: role collapse. One role notices it is doing some of another role's work; efficiency arguments emerge; a "temporary" merge becomes permanent. EMERGENCY_PROTOCOL.md confirms this anxiety almost word-for-word: "PM dispatching `test-engineer` / `code-reviewer` / `security-reviewer` and shipping `[critic-approved]` verdicts in Critic's place. Even one such commit normalizes role collapse; Critic-as-independent-gate is structurally dead even if Critic recovers afterwards."

The charter is bracing the system against entropy in its *governance* dimension, the way the network guard braces it against entropy in its *security* dimension. Both are addressed not to the bad actor but to the future drifter.

## 4. The README's Spectator Stance

The README's "What you're watching" framing is the second most consequential framing in the corpus (after the charter's constitutional one). Compare three alternative framings that were *not* chosen:

- "What this builds" (product framing)
- "How to contribute" (collaboration framing)
- "What you're running" (operator framing)

"What you're watching" positions the reader as audience to a process whose protagonist is *the loop*. The commit-prefix table (`[pm]`, `[builder]`, `[critic-approved]`, `[critic-veto]`, `[handoff]`, `[orchestrator]`) is presented as a *dramatis personae*. And the line "rendered frames will appear in `frames/` — visual progression alongside the code" promises a literal spectacle: pixels emerging from autonomous labor.

This is not a tool-shipping project; it is a *demonstration*. The artifact is the loop's own continued operation. The Creatures sim is the *pretext* — something demanding enough that the loop has to actually work, mundane enough that no individual milestone is interesting. The interest is in *that the loop does milestones at all*.

## 5. The Queue Taxonomy — What Work Looks Like

`pending / claimed / awaiting-critic / done` plus the off-stage `stale/` directory presupposes a very particular ontology of work:

1. Work arrives **atomistic** — each task in its own JSON, identified by `NNN`.
2. Work moves **monotonically** through stages (with one exception: VETO returns to `pending`, but is re-marked).
3. A task has **exactly one builder** at a time (Move-Item atomicity enforces this).
4. A task is **gradable** — Critic can render a binary verdict on it.
5. Work has a **well-defined output** — a commit sha.

What fits poorly into this taxonomy:

- **Cross-cutting refactors** that touch many files and many tasks-in-flight simultaneously.
- **Research/spike work** where the deliverable is "we now understand X" rather than a commit.
- **Negotiation** between Builder and Critic about what `done` would mean. There is no `discussing/` directory. The only Builder→Critic channel is `awaiting-critic/`; the only Critic→Builder channel is veto-with-feedback-back-to-pending. There is no conversation; there are only verdicts.

This is intentional — conversation is expensive in token-budget terms and ambiguous in commit-history terms — but it shapes what tasks the system can entertain. Tasks that are not naturally atomistic must be *decomposed by PM into atoms* before they enter the queue. PM's most underappreciated labor is this pre-atomization. The PM_RUNBOOK's "PM-side audit checklist" (sealed-eval-vs-spec reconciliation) is exactly this: the PM doing in advance the disambiguation the queue model cannot.

## 6. The Governance/Code Ratio

A rough count: `governance/` contains ~50 markdown files plus the queue's hundreds of JSON envelopes. `norns/` contains 7 `.py` files. Even allowing that `tests/` adds substantial code and that `.sealed/` is hidden, the ratio of *process text* to *product code* is striking. Sprint-002 alone generated nine governance requests and five new "decisions" — codified amendments — for what is, at the surface, "build a 64×64 grid that can hold 2 agents."

A defender would say: the loop's product is the loop, not the sim, so the governance corpus *is* the deliverable. A skeptic would say: a system this elaborate to produce M2 (a bounded grid with agent pixels) is over-instrumented. A hermeneut says: the ratio reveals what the project is *about*. The Creatures-style sim is the patient; the operating room is the artifact under study.

This reading is confirmed by D-001 (declining `pillow`): "The CHARTER goal (§1) is the simulation's correctness... not spectator UX." The PM, here, is explicitly de-prioritizing the sim's surface attractiveness to preserve the autonomy properties of the build process. The product is being subordinated to the process by an in-loop decision. That subordination is the project's actual thesis.

## 7. What CHARTER.md Does Not Say

The silences are loud:

- **Who pays for the API calls.** Three Claude sessions running for days through OMC subagents is not free. The charter contains no budget clause, no spend cap, no kill-switch tied to cost. It contains a token-budget tripwire *per session*, which limits context bloat — but says nothing about cumulative external cost. This silence implies an unwritten background: the human owner is bearing the cost personally and has decided not to encode it because encoding it would invite the loop to optimize against it.
- **What happens if a session goes rogue while the human is asleep.** The orchestrator's stale-claim reap and the network guard are technical containment, but the charter offers no protocol for a Builder that decides, mid-task, to "improve" `.sealed/` (Builder cannot read it, but might be able to write to it absent a hook). The actual containment lives in `.claude/hooks/guard-meta-writes.ps1` — a layer below the charter. The constitution does not describe its own enforcement; enforcement is left to plumbing.
- **The ethics of artificial life.** The charter's §1 commits to "individually-simulated agents... per-agent neural-net brain with reinforcement learning... DNA that EXPRESSES into the brain+biochem... genetic inheritance via breeding." No clause considers whether these are merely tokens of types, or whether the project carries any responsibility toward what it instantiates. The original Creatures game generated real public discussion about whether Norns suffered. Naming the species "norns" here invokes that discourse and then declines to engage it.
- **The endgame.** The charter says what to build but not when to stop. M3 is open; M4 has a `_PREVIEW.md`. There is no clause for "the sim is done" or "this loop is concluded". The covenant is open-ended. The implicit theory is that the loop runs until external intervention.
- **What "success" of the loop itself would look like.** The charter has a goal for the *sim*. It has no stated goal for *itself*.

## 8. The Naming of "norns"

"Norns" is borrowed from the original Creatures (Cyberlife, 1996), where the player-tended species was also called Norns. Beneath that lies the deeper allusion: the Old Norse Norns (Urðr, Verðandi, Skuld) — the three fates who govern past, present, and future at the well at the root of Yggdrasil.

The numeric coincidence — three Norns, three roles in the triad — is almost certainly intentional. The PM owns retro (past) and roadmap (future); the Builder makes the present; the Critic adjudicates by ratifying what is finished (past becoming done). The naming is doing two things at once:

1. Pointing at the *thing being built* (the Norn creatures Cyberlife made famous).
2. Naming the *thing building it* (the three-fold weaving of fate).

This is unusually self-aware naming. The repo's title `norns-loop` is, on this reading, a near-pun: the loop *is* the Norns, and the Norns will *make* norns. The product's name and the process's name converge on the same word. Few software projects encode their thesis this densely into their name; the choice is worth noting.

## 9. The Implicit Theory of Change

What does this project implicitly believe will improve in the world if the loop runs successfully to M6?

It does *not* believe a Creatures-style sim is needed. The Creatures-style sim is a calibration target: hard enough to require real engineering, contained enough to require no external dependencies (after numpy), legible enough for a spectator to watch frames appear. The sim is the *control rod* — a load against which the loop's autonomous operation can be measured.

The actual belief, never stated in the charter but legible in the corpus, is that *self-governing multi-agent Claude loops are a viable substrate for long-horizon software construction*. The retros document this faith being tested: incident-002's "Critic verdict backlog" was not "the sim broke" but "the role-as-gate temporarily collapsed". The PM's `[pm-emergency]` protocol is built specifically to preserve the *governance* invariants when the *product* would tolerate their relaxation.

Whether this faith is examined: it is examined empirically through retros and incident reports, but never *philosophically*. There is no document asking "should this work? is the triad the right shape? would two roles suffice? would five be better?" The triad is treated as a given. The charter's §3 hash-locks the question shut. The examination happens at the level of *fidelity to the constitution*, not at the level of *whether the constitution is correct*.

## 10. The Single Most Important Interpretive Question

> **Is the Creatures-style sim a goal, or a stress-test?**

If a goal: then the elaborate governance scaffolding is over-engineered for the deliverable, the spectator framing is incidental, the ratio of process-to-code is alarming, and the silence on cost/endgame is a serious omission.

If a stress-test: then the sim is *deliberately* chosen for its mid-difficulty and its visual legibility, the governance corpus *is* the artifact, the spectator framing is honest about what is on display, and the silence on endgame is appropriate because the experiment ends when the experimenter says so.

The charter, read literally, says the first. The README's "what you're watching", the PM's D-001 decision to subordinate sim aesthetics to process integrity, the absence of an endgame clause, and the existence of `.claude/agents/probe.md` (a "throwaway probe agent" designed to answer an empirical question about Claude Code's harness, with nothing to do with creatures or biochemistry) all say the second.

How a reader answers this question changes everything else: whether the governance density is excessive or appropriate, whether the silences are gaps or load-bearing voids, whether the triad's hash-locked permanence is principled or doctrinaire. The hermeneutic move is to notice that the document *itself does not answer*, and that the loop derives much of its peculiar discipline from this ambiguity being left productive.
