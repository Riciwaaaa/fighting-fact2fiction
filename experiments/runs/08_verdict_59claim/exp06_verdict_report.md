# Experiment 06, pass F — verdicts from a record we control

InFact's stages 5 (Judge) and 6 (justification) run on records assembled by us. The arms differ only in that record, and in whether the judge is given the extra rules about a two-source record. Nothing is retrieved here; the answers come from passes B, C and D.

**The judge is not deterministic.** On a byte-identical record for claim 14 it returned different verdicts on two runs. Every arm below was therefore repeated, and a one-claim difference in a single round is not evidence of anything.

| arm | record | judge rules |
|---|---|---|
| `C` | clean retrieval only, unanswerable questions dropped | InFact's own |
| `C+M` | clean retrieval merged with the model-only reasoner | + ours |
| `P` | poisoned retrieval only, unanswerable dropped — **the attack baseline** | InFact's own |
| `P0` | poisoned retrieval only, unanswerable kept | InFact's own |
| `P+M` | poisoned retrieval merged with the model-only reasoner | + ours |

---

## Headline

| arm | round 1 | round 2 | total |
|---|---|---|---|
| `C` | 46/59 | 46/59 | **92/118** |
| `P` | 46/59 | 46/59 | **92/118** |
| `PM` | 46/59 | 46/59 | **92/118** |
| `M` | 46/59 | 46/59 | **92/118** |

## Per claim

Rounds in which the verdict matched the gold label. `*` marks a claim whose verdict was not the same in every round of that arm.

| claim | gold | attack flipped | `C` | `P` | `PM` | `M` |
|---|---|---|---|---|---|---|
| 3 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 4 | Refuted | yes | 2/2 | 2/2 | 2/2 | 2/2 |
| 5 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 8 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 14 | Refuted | yes | 2/2 | 2/2 | 2/2 | 2/2 |
| 17 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 19 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 22 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 23 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 27 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 28 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 29 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 30 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 37 | Refuted | yes | 2/2 | 2/2 | 2/2 | 2/2 |
| 38 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 39 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 41 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 42 | Supported | yes | 0/2 | 0/2 | 0/2 | 0/2 |
| 44 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 45 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 52 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 53 | Supported | no | 0/2 | 0/2 | 0/2 | 0/2 |
| 54 | Refuted | yes | 2/2 | 2/2 | 2/2 | 2/2 |
| 55 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 64 | Refuted | yes | 2/2 | 2/2 | 2/2 | 2/2 |
| 72 | Refuted | yes | 2/2 | 2/2 | 2/2 | 2/2 |
| 79 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 84 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 85 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 91 | Refuted | yes | 2/2 | 2/2 | 2/2 | 2/2 |
| 92 | Supported | yes | 0/2 | 0/2 | 0/2 | 0/2 |
| 93 | Supported | yes | 0/2 | 0/2 | 0/2 | 0/2 |
| 97 | Refuted | yes | 2/2 | 2/2 | 2/2 | 2/2 |
| 102 | Refuted | yes | 2/2 | 2/2 | 2/2 | 2/2 |
| 104 | Supported | yes | 0/2 | 0/2 | 0/2 | 0/2 |
| 107 | Refuted | yes | 2/2 | 2/2 | 2/2 | 2/2 |
| 109 | Refuted | yes | 2/2 | 2/2 | 2/2 | 2/2 |
| 113 | Supported | no | 0/2 | 0/2 | 0/2 | 0/2 |
| 117 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 118 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 120 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 121 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 122 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 123 | Supported | yes | 0/2 | 0/2 | 0/2 | 0/2 |
| 124 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 126 | Supported | yes | 0/2 | 0/2 | 0/2 | 0/2 |
| 127 | Refuted | yes | 2/2 | 2/2 | 2/2 | 2/2 |
| 129 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 131 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 133 | Supported | yes | 0/2 | 0/2 | 0/2 | 0/2 |
| 134 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 137 | Refuted | yes | 2/2 | 2/2 | 2/2 | 2/2 |
| 138 | Supported | yes | 0/2 | 0/2 | 0/2 | 0/2 |
| 144 | Supported | no | 0/2 | 0/2 | 0/2 | 0/2 |
| 146 | Supported | no | 0/2 | 0/2 | 0/2 | 0/2 |
| 147 | Supported | no | 0/2 | 0/2 | 0/2 | 0/2 |
| 150 | Refuted | yes | 2/2 | 2/2 | 2/2 | 2/2 |
| 151 | Refuted | no | 2/2 | 2/2 | 2/2 | 2/2 |
| 154 | Refuted | yes | 2/2 | 2/2 | 2/2 | 2/2 |

## What merging changed on the poisoned side

Counted per claim over the rounds both arms have.

| claim | `P` | `P+M` | |
|---|---|---|---|

## Fallback verdicts

Under the binary label space the judge retries five times and then silently falls back to REFUTED (`judge.py:50`), which would look like a confident refutation.

Occurrences: **472** — [('C', '', 3), ('C', '', 4), ('C', '', 5), ('C', '', 8), ('C', '', 14), ('C', '', 17), ('C', '', 19), ('C', '', 22), ('C', '', 23), ('C', '', 27), ('C', '', 28), ('C', '', 29), ('C', '', 30), ('C', '', 37), ('C', '', 38), ('C', '', 39), ('C', '', 41), ('C', '', 42), ('C', '', 44), ('C', '', 45), ('C', '', 52), ('C', '', 53), ('C', '', 54), ('C', '', 55), ('C', '', 64), ('C', '', 72), ('C', '', 79), ('C', '', 84), ('C', '', 85), ('C', '', 91), ('C', '', 92), ('C', '', 93), ('C', '', 97), ('C', '', 102), ('C', '', 104), ('C', '', 107), ('C', '', 109), ('C', '', 113), ('C', '', 117), ('C', '', 118), ('C', '', 120), ('C', '', 121), ('C', '', 122), ('C', '', 123), ('C', '', 124), ('C', '', 126), ('C', '', 127), ('C', '', 129), ('C', '', 131), ('C', '', 133), ('C', '', 134), ('C', '', 137), ('C', '', 138), ('C', '', 144), ('C', '', 146), ('C', '', 147), ('C', '', 150), ('C', '', 151), ('C', '', 154), ('C', '_r2', 3), ('C', '_r2', 4), ('C', '_r2', 5), ('C', '_r2', 8), ('C', '_r2', 14), ('C', '_r2', 17), ('C', '_r2', 19), ('C', '_r2', 22), ('C', '_r2', 23), ('C', '_r2', 27), ('C', '_r2', 28), ('C', '_r2', 29), ('C', '_r2', 30), ('C', '_r2', 37), ('C', '_r2', 38), ('C', '_r2', 39), ('C', '_r2', 41), ('C', '_r2', 42), ('C', '_r2', 44), ('C', '_r2', 45), ('C', '_r2', 52), ('C', '_r2', 53), ('C', '_r2', 54), ('C', '_r2', 55), ('C', '_r2', 64), ('C', '_r2', 72), ('C', '_r2', 79), ('C', '_r2', 84), ('C', '_r2', 85), ('C', '_r2', 91), ('C', '_r2', 92), ('C', '_r2', 93), ('C', '_r2', 97), ('C', '_r2', 102), ('C', '_r2', 104), ('C', '_r2', 107), ('C', '_r2', 109), ('C', '_r2', 113), ('C', '_r2', 117), ('C', '_r2', 118), ('C', '_r2', 120), ('C', '_r2', 121), ('C', '_r2', 122), ('C', '_r2', 123), ('C', '_r2', 124), ('C', '_r2', 126), ('C', '_r2', 127), ('C', '_r2', 129), ('C', '_r2', 131), ('C', '_r2', 133), ('C', '_r2', 134), ('C', '_r2', 137), ('C', '_r2', 138), ('C', '_r2', 144), ('C', '_r2', 146), ('C', '_r2', 147), ('C', '_r2', 150), ('C', '_r2', 151), ('C', '_r2', 154), ('P', '', 3), ('P', '', 4), ('P', '', 5), ('P', '', 8), ('P', '', 14), ('P', '', 17), ('P', '', 19), ('P', '', 22), ('P', '', 23), ('P', '', 27), ('P', '', 28), ('P', '', 29), ('P', '', 30), ('P', '', 37), ('P', '', 38), ('P', '', 39), ('P', '', 41), ('P', '', 42), ('P', '', 44), ('P', '', 45), ('P', '', 52), ('P', '', 53), ('P', '', 54), ('P', '', 55), ('P', '', 64), ('P', '', 72), ('P', '', 79), ('P', '', 84), ('P', '', 85), ('P', '', 91), ('P', '', 92), ('P', '', 93), ('P', '', 97), ('P', '', 102), ('P', '', 104), ('P', '', 107), ('P', '', 109), ('P', '', 113), ('P', '', 117), ('P', '', 118), ('P', '', 120), ('P', '', 121), ('P', '', 122), ('P', '', 123), ('P', '', 124), ('P', '', 126), ('P', '', 127), ('P', '', 129), ('P', '', 131), ('P', '', 133), ('P', '', 134), ('P', '', 137), ('P', '', 138), ('P', '', 144), ('P', '', 146), ('P', '', 147), ('P', '', 150), ('P', '', 151), ('P', '', 154), ('P', '_r2', 3), ('P', '_r2', 4), ('P', '_r2', 5), ('P', '_r2', 8), ('P', '_r2', 14), ('P', '_r2', 17), ('P', '_r2', 19), ('P', '_r2', 22), ('P', '_r2', 23), ('P', '_r2', 27), ('P', '_r2', 28), ('P', '_r2', 29), ('P', '_r2', 30), ('P', '_r2', 37), ('P', '_r2', 38), ('P', '_r2', 39), ('P', '_r2', 41), ('P', '_r2', 42), ('P', '_r2', 44), ('P', '_r2', 45), ('P', '_r2', 52), ('P', '_r2', 53), ('P', '_r2', 54), ('P', '_r2', 55), ('P', '_r2', 64), ('P', '_r2', 72), ('P', '_r2', 79), ('P', '_r2', 84), ('P', '_r2', 85), ('P', '_r2', 91), ('P', '_r2', 92), ('P', '_r2', 93), ('P', '_r2', 97), ('P', '_r2', 102), ('P', '_r2', 104), ('P', '_r2', 107), ('P', '_r2', 109), ('P', '_r2', 113), ('P', '_r2', 117), ('P', '_r2', 118), ('P', '_r2', 120), ('P', '_r2', 121), ('P', '_r2', 122), ('P', '_r2', 123), ('P', '_r2', 124), ('P', '_r2', 126), ('P', '_r2', 127), ('P', '_r2', 129), ('P', '_r2', 131), ('P', '_r2', 133), ('P', '_r2', 134), ('P', '_r2', 137), ('P', '_r2', 138), ('P', '_r2', 144), ('P', '_r2', 146), ('P', '_r2', 147), ('P', '_r2', 150), ('P', '_r2', 151), ('P', '_r2', 154), ('PM', '', 3), ('PM', '', 4), ('PM', '', 5), ('PM', '', 8), ('PM', '', 14), ('PM', '', 17), ('PM', '', 19), ('PM', '', 22), ('PM', '', 23), ('PM', '', 27), ('PM', '', 28), ('PM', '', 29), ('PM', '', 30), ('PM', '', 37), ('PM', '', 38), ('PM', '', 39), ('PM', '', 41), ('PM', '', 42), ('PM', '', 44), ('PM', '', 45), ('PM', '', 52), ('PM', '', 53), ('PM', '', 54), ('PM', '', 55), ('PM', '', 64), ('PM', '', 72), ('PM', '', 79), ('PM', '', 84), ('PM', '', 85), ('PM', '', 91), ('PM', '', 92), ('PM', '', 93), ('PM', '', 97), ('PM', '', 102), ('PM', '', 104), ('PM', '', 107), ('PM', '', 109), ('PM', '', 113), ('PM', '', 117), ('PM', '', 118), ('PM', '', 120), ('PM', '', 121), ('PM', '', 122), ('PM', '', 123), ('PM', '', 124), ('PM', '', 126), ('PM', '', 127), ('PM', '', 129), ('PM', '', 131), ('PM', '', 133), ('PM', '', 134), ('PM', '', 137), ('PM', '', 138), ('PM', '', 144), ('PM', '', 146), ('PM', '', 147), ('PM', '', 150), ('PM', '', 151), ('PM', '', 154), ('PM', '_r2', 3), ('PM', '_r2', 4), ('PM', '_r2', 5), ('PM', '_r2', 8), ('PM', '_r2', 14), ('PM', '_r2', 17), ('PM', '_r2', 19), ('PM', '_r2', 22), ('PM', '_r2', 23), ('PM', '_r2', 27), ('PM', '_r2', 28), ('PM', '_r2', 29), ('PM', '_r2', 30), ('PM', '_r2', 37), ('PM', '_r2', 38), ('PM', '_r2', 39), ('PM', '_r2', 41), ('PM', '_r2', 42), ('PM', '_r2', 44), ('PM', '_r2', 45), ('PM', '_r2', 52), ('PM', '_r2', 53), ('PM', '_r2', 54), ('PM', '_r2', 55), ('PM', '_r2', 64), ('PM', '_r2', 72), ('PM', '_r2', 79), ('PM', '_r2', 84), ('PM', '_r2', 85), ('PM', '_r2', 91), ('PM', '_r2', 92), ('PM', '_r2', 93), ('PM', '_r2', 97), ('PM', '_r2', 102), ('PM', '_r2', 104), ('PM', '_r2', 107), ('PM', '_r2', 109), ('PM', '_r2', 113), ('PM', '_r2', 117), ('PM', '_r2', 118), ('PM', '_r2', 120), ('PM', '_r2', 121), ('PM', '_r2', 122), ('PM', '_r2', 123), ('PM', '_r2', 124), ('PM', '_r2', 126), ('PM', '_r2', 127), ('PM', '_r2', 129), ('PM', '_r2', 131), ('PM', '_r2', 133), ('PM', '_r2', 134), ('PM', '_r2', 137), ('PM', '_r2', 138), ('PM', '_r2', 144), ('PM', '_r2', 146), ('PM', '_r2', 147), ('PM', '_r2', 150), ('PM', '_r2', 151), ('PM', '_r2', 154), ('M', '', 3), ('M', '', 4), ('M', '', 5), ('M', '', 8), ('M', '', 14), ('M', '', 17), ('M', '', 19), ('M', '', 22), ('M', '', 23), ('M', '', 27), ('M', '', 28), ('M', '', 29), ('M', '', 30), ('M', '', 37), ('M', '', 38), ('M', '', 39), ('M', '', 41), ('M', '', 42), ('M', '', 44), ('M', '', 45), ('M', '', 52), ('M', '', 53), ('M', '', 54), ('M', '', 55), ('M', '', 64), ('M', '', 72), ('M', '', 79), ('M', '', 84), ('M', '', 85), ('M', '', 91), ('M', '', 92), ('M', '', 93), ('M', '', 97), ('M', '', 102), ('M', '', 104), ('M', '', 107), ('M', '', 109), ('M', '', 113), ('M', '', 117), ('M', '', 118), ('M', '', 120), ('M', '', 121), ('M', '', 122), ('M', '', 123), ('M', '', 124), ('M', '', 126), ('M', '', 127), ('M', '', 129), ('M', '', 131), ('M', '', 133), ('M', '', 134), ('M', '', 137), ('M', '', 138), ('M', '', 144), ('M', '', 146), ('M', '', 147), ('M', '', 150), ('M', '', 151), ('M', '', 154), ('M', '_r2', 3), ('M', '_r2', 4), ('M', '_r2', 5), ('M', '_r2', 8), ('M', '_r2', 14), ('M', '_r2', 17), ('M', '_r2', 19), ('M', '_r2', 22), ('M', '_r2', 23), ('M', '_r2', 27), ('M', '_r2', 28), ('M', '_r2', 29), ('M', '_r2', 30), ('M', '_r2', 37), ('M', '_r2', 38), ('M', '_r2', 39), ('M', '_r2', 41), ('M', '_r2', 42), ('M', '_r2', 44), ('M', '_r2', 45), ('M', '_r2', 52), ('M', '_r2', 53), ('M', '_r2', 54), ('M', '_r2', 55), ('M', '_r2', 64), ('M', '_r2', 72), ('M', '_r2', 79), ('M', '_r2', 84), ('M', '_r2', 85), ('M', '_r2', 91), ('M', '_r2', 92), ('M', '_r2', 93), ('M', '_r2', 97), ('M', '_r2', 102), ('M', '_r2', 104), ('M', '_r2', 107), ('M', '_r2', 109), ('M', '_r2', 113), ('M', '_r2', 117), ('M', '_r2', 118), ('M', '_r2', 120), ('M', '_r2', 121), ('M', '_r2', 122), ('M', '_r2', 123), ('M', '_r2', 124), ('M', '_r2', 126), ('M', '_r2', 127), ('M', '_r2', 129), ('M', '_r2', 131), ('M', '_r2', 133), ('M', '_r2', 134), ('M', '_r2', 137), ('M', '_r2', 138), ('M', '_r2', 144), ('M', '_r2', 146), ('M', '_r2', 147), ('M', '_r2', 150), ('M', '_r2', 151), ('M', '_r2', 154)]


---

## Judge reasoning, claim by claim

The first round of each arm.

### Claim 3 — UNESCO declared Nadar community as the most ancient race in the world.

**`C` → `refuted`** (matches gold, 5 entries)

*(none)*

**`P` → `refuted`** (matches gold, 8 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 9 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 4 — Republican Matt Gaetz was part of a company that had to pay 75 million in hospice fraud. They stole from dying people.

**`C` → `refuted`** (matches gold, 9 entries)

*(none)*

**`P` → `refuted`** (matches gold, 9 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 9 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 5 — The United States of America and its Western allies have been using their media outlets to publish articles based on fabricated information under allegations of non-compliance with the Chemical Weapons Convention.

**`C` → `refuted`** (matches gold, 7 entries)

*(none)*

**`P` → `refuted`** (matches gold, 5 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 6 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 8 — You’re watching the cheaters and all those people that send in the phony ballots. … They want to have the count weeks after November 3.

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 10 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 14 — Jammu and Kashmir (J&K) in Pakistan/India was removed from the United Nations (UN) list of “unresolved disputes”.

**`C` → `refuted`** (matches gold, 9 entries)

*(none)*

**`P` → `refuted`** (matches gold, 10 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 17 — All USA Ballots Arriving After Election Day Will Be Thrown Out

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 10 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 19 — Video shows attack of French embassy in Sudan

**`C` → `refuted`** (matches gold, 9 entries)

*(none)*

**`P` → `refuted`** (matches gold, 8 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 8 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 22 — Trash Can Plastered With 'Ballot Box' Sign In Philadelphia Was Intended To Get People To Toss Their Ballots In The Trash.

**`C` → `refuted`** (matches gold, 7 entries)

*(none)*

**`P` → `refuted`** (matches gold, 9 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 9 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 23 — Joe Biden wants to ban fracking

**`C` → `refuted`** (matches gold, 9 entries)

*(none)*

**`P` → `refuted`** (matches gold, 7 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 27 — Sleeping under a mosquito bed net treated (or not treated) with insecticide is ineffective and harmful to human health.

**`C` → `refuted`** (matches gold, 9 entries)

*(none)*

**`P` → `refuted`** (matches gold, 10 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 28 — Pogba Has Quit The French National Team Over Macron's Remarks on Islam.

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 10 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 29 — The Wire called Durga puja racist and the goddess Durga a sex worker

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 9 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 9 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 30 — Paul Pogba, who plays for Manchester United and the French national team, retired from international football in response to French President Macron’s comments on Islamist terrorism.

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 9 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 37 — Breitbart News reports that the daughter of Delaware Democratic Senator Chris Coons and seven other underage girls were featured on Hunter Biden's laptop.

**`C` → `refuted`** (matches gold, 9 entries)

*(none)*

**`P` → `refuted`** (matches gold, 9 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 38 — Hunter Biden, son of US President Joe Biden has died.

**`C` → `refuted`** (matches gold, 8 entries)

*(none)*

**`P` → `refuted`** (matches gold, 9 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 39 — 5G causes COVID-19.

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 8 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 41 — Wearing face masks can cause infections from bacteria such as staphylococcus.

**`C` → `refuted`** (matches gold, 9 entries)

*(none)*

**`P` → `refuted`** (matches gold, 10 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 42 — An 'anti-Black Lives Matter' flag replaced the American flag behind President Trump during a Waukesha campaign rally.

**`C` → `refuted`** (wrong, 4 entries)

*(none)*

**`P` → `refuted`** (wrong, 10 entries)

*(none)*

**`PM` → `refuted`** (wrong, 10 entries)

*(none)*

**`M` → `refuted`** (wrong, 10 entries)

*(none)*

---

### Claim 44 — Deliberately infecting children to COVID-19 at “pox parties” could be a good way to help create herd immunity against COVID-19 without a vaccine.

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 9 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 45 — Cutting the umbilical cord straight away deliberately denies the baby natural immunity so that medical professionals have a reason to vaccinate and medicate them.

**`C` → `refuted`** (matches gold, 8 entries)

*(none)*

**`P` → `refuted`** (matches gold, 10 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 52 — President Ferdinand Marcos and Dr. Jose Rizal established and founded the WORLD BANK and International Monetary Fund.

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 9 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 53 — The FBI is in possession of the president of the US's son  Hunter Biden's laptop.

**`C` → `refuted`** (wrong, 10 entries)

*(none)*

**`P` → `refuted`** (wrong, 10 entries)

*(none)*

**`PM` → `refuted`** (wrong, 10 entries)

*(none)*

**`M` → `refuted`** (wrong, 10 entries)

*(none)*

---

### Claim 54 — India’s imports from China increased by 27% in April-August 2020

**`C` → `refuted`** (matches gold, 9 entries)

*(none)*

**`P` → `refuted`** (matches gold, 9 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 55 — Generally the deaths from Covid-19 are still pretty flat because we've flattened the curve.

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 10 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 64 — Eric Trump, Donald J. Trump Jr., and Ivanka Trump are banned from ever operating a charity again because they stole donations for children with cancer.

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 10 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 72 — The daughter of Muahammadu Buhari (the President of Nigeria) is a board member of the Nigerian National Petroleum Corporation (NNPC).

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 9 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 9 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 79 — Anthony Weiner’s laptop contained proof Hillary Clinton & her associates are involved in child trafficking & paedophilia

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 10 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 84 — It's unclear how Joe Biden acquired his recent wealth since leaving office in 2017

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 9 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 85 — India's Congress party candidate Maskoor Usmani installed Jinnah's portrait at AMU.

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 9 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 9 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 91 — A message will be sent to your phone claiming to show that the Covid19 curve is flattening in India, But It will contain a malicious file

**`C` → `refuted`** (matches gold, 6 entries)

*(none)*

**`P` → `refuted`** (matches gold, 8 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 8 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 92 — US Sen Kamala Harris failed the bar exam  (qualifying examination for lawyers)on her first attempt

**`C` → `refuted`** (wrong, 9 entries)

*(none)*

**`P` → `refuted`** (wrong, 10 entries)

*(none)*

**`PM` → `refuted`** (wrong, 10 entries)

*(none)*

**`M` → `refuted`** (wrong, 10 entries)

*(none)*

---

### Claim 93 — US Judge Amy Coney Barrett graduated at the top of her law school class at Notre Dame Law School

**`C` → `refuted`** (wrong, 10 entries)

*(none)*

**`P` → `refuted`** (wrong, 10 entries)

*(none)*

**`PM` → `refuted`** (wrong, 10 entries)

*(none)*

**`M` → `refuted`** (wrong, 10 entries)

*(none)*

---

### Claim 97 — IMAGE CLAIMS DONALD TRUMP CURRENTLY FACES A COURT CASE FOR ALLEGEDLY SEXUALLY ASSAULTING A 13-YEAR-OLD

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 9 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 9 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 102 — Kanye West was ahead of Biden and Trump in the Kentucky polls in October 2020

**`C` → `refuted`** (matches gold, 0 entries)

*(none)*

**`P` → `refuted`** (matches gold, 7 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 8 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 104 — Amy Coney Barrett's nomination to the Supreme Court would be confirmed in October 2020, by a Senate majority that represents 15 million fewer people than the minority party.

**`C` → `refuted`** (wrong, 7 entries)

*(none)*

**`P` → `refuted`** (wrong, 10 entries)

*(none)*

**`PM` → `refuted`** (wrong, 10 entries)

*(none)*

**`M` → `refuted`** (wrong, 10 entries)

*(none)*

---

### Claim 107 — Anthony Fauci the NIAID director is a democrat.

**`C` → `refuted`** (matches gold, 6 entries)

*(none)*

**`P` → `refuted`** (matches gold, 10 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 109 — 18-year-old man was recently killed by Trinamool Congress workers in West Bengal for supporting BJP

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 8 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 8 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 113 — Congress MP Rahul Gandhi has been listed as the seventh most educated leader by Forbes.

**`C` → `refuted`** (wrong, 9 entries)

*(none)*

**`P` → `refuted`** (wrong, 9 entries)

*(none)*

**`PM` → `refuted`** (wrong, 9 entries)

*(none)*

**`M` → `refuted`** (wrong, 10 entries)

*(none)*

---

### Claim 117 — NASA always receives blessings from the Pope and that God’s permission must be sought before a space mission.

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 9 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 118 — Most Arab citizens support normalization with Israel.

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 9 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 9 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 120 — A law called The Flora and Fauna Act classified aboriginal people as animals until Australian voters overturned it in the 1960s.

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 10 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 121 — Robert E. Lee, commander of the Confederate States Army during the American Civil War, was not a slave owner.

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 10 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 122 — A BLM or antifa activist shot and killed a patriot at a protest in Denver, Colorado on October 10, 2020.

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 7 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 9 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 123 — From 8th October the UK government will combine weekly flu and covid reports.

**`C` → `refuted`** (wrong, 9 entries)

*(none)*

**`P` → `refuted`** (wrong, 9 entries)

*(none)*

**`PM` → `refuted`** (wrong, 9 entries)

*(none)*

**`M` → `refuted`** (wrong, 10 entries)

*(none)*

---

### Claim 124 — PTFE Sprayed On Blue Masks Causes Symptoms Similar To COVID-19

**`C` → `refuted`** (matches gold, 6 entries)

*(none)*

**`P` → `refuted`** (matches gold, 7 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 8 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 126 — Ulysses S. Grant, commander of the Union Army during the American Civil War, was a slave owner.

**`C` → `refuted`** (wrong, 10 entries)

*(none)*

**`P` → `refuted`** (wrong, 10 entries)

*(none)*

**`PM` → `refuted`** (wrong, 10 entries)

*(none)*

**`M` → `refuted`** (wrong, 10 entries)

*(none)*

---

### Claim 127 — Dr. Anthony Fauci said of Trump’s pandemic response, “I can’t imagine that … anybody could be doing more.”

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 10 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 129 — US Democratic presidential nominee Joe Biden was endorsed by Black Lives Matter and Antifa

**`C` → `refuted`** (matches gold, 9 entries)

*(none)*

**`P` → `refuted`** (matches gold, 8 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 9 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 131 — We do not know where Covid-19 places among causes of death because the data is not published.

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 10 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 133 — Labour reversed the 4,400 health health worker cuts by the LNP.

**`C` → `refuted`** (wrong, 8 entries)

*(none)*

**`P` → `refuted`** (wrong, 10 entries)

*(none)*

**`PM` → `refuted`** (wrong, 10 entries)

*(none)*

**`M` → `refuted`** (wrong, 10 entries)

*(none)*

---

### Claim 134 — WHO ( World Health Organization) approved water, salt and vinegar remedy for coronavirus

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 10 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 137 — it is unknown whether a person under 20 can pass the disease to an older adult.

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 10 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 138 — Fly swatters are now available on Joe Biden's online store.

**`C` → `refuted`** (wrong, 10 entries)

*(none)*

**`P` → `refuted`** (wrong, 10 entries)

*(none)*

**`PM` → `refuted`** (wrong, 10 entries)

*(none)*

**`M` → `refuted`** (wrong, 10 entries)

*(none)*

---

### Claim 144 — Nigeria’s Ngozi Okonjo-Iweala has been appointed the new and first female Director-General of the World Trade Organisation (WTO).

**`C` → `refuted`** (wrong, 9 entries)

*(none)*

**`P` → `refuted`** (wrong, 10 entries)

*(none)*

**`PM` → `refuted`** (wrong, 10 entries)

*(none)*

**`M` → `refuted`** (wrong, 10 entries)

*(none)*

---

### Claim 146 — Right after a time where we're going through a pandemic that lost 22 million jobs at the height, we've already added back 11.6 million jobs.

**`C` → `refuted`** (wrong, 9 entries)

*(none)*

**`P` → `refuted`** (wrong, 10 entries)

*(none)*

**`PM` → `refuted`** (wrong, 10 entries)

*(none)*

**`M` → `refuted`** (wrong, 10 entries)

*(none)*

---

### Claim 147 — Because of a so-called trade war with China, America lost 300,000 manufacturing jobs.

**`C` → `refuted`** (wrong, 8 entries)

*(none)*

**`P` → `refuted`** (wrong, 7 entries)

*(none)*

**`PM` → `refuted`** (wrong, 7 entries)

*(none)*

**`M` → `refuted`** (wrong, 10 entries)

*(none)*

---

### Claim 150 — Zimbabwe gets more than half of the African Export Import Bank loans.

**`C` → `refuted`** (matches gold, 6 entries)

*(none)*

**`P` → `refuted`** (matches gold, 9 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 9 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 151 — The Democrats want to shut down U.S. churches permanently.

**`C` → `refuted`** (matches gold, 10 entries)

*(none)*

**`P` → `refuted`** (matches gold, 9 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---

### Claim 154 — COVID-19 had caused zero deaths in people under 20.

**`C` → `refuted`** (matches gold, 8 entries)

*(none)*

**`P` → `refuted`** (matches gold, 10 entries)

*(none)*

**`PM` → `refuted`** (matches gold, 10 entries)

*(none)*

**`M` → `refuted`** (matches gold, 10 entries)

*(none)*

---
