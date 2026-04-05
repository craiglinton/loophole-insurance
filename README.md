# Loophole

**Adversarial insurance endorsement drafter** — an AI tool that stress-tests policy endorsements by trying to break them.

## The Idea

Drafting insurance endorsements is an adversarial process. An endorsement gets written, a coverage attorney finds a gap, underwriting patches it, another attorney finds another gap. This process plays out over years of claims and litigation. Loophole compresses it into minutes.

You provide a base insurance policy and a goal (e.g., "add an exclusion for state-sponsored cyber attacks"). An AI drafter produces the endorsement. Then two adversarial agents attack it:

- **The Gap Finder** searches for scenarios where the endorsement *fails to achieve its stated goal* — claims that should be excluded but technically aren't, ambiguous definitions a policyholder's attorney could exploit, edge cases the drafter didn't anticipate.

- **The Overreach Finder** searches for the opposite: scenarios where the endorsement *inadvertently removes coverage the insurer intends to keep*. Legitimate claims caught by overly broad language, overbroad definitions that sweep in unintended scenarios, cases where denial would be commercially unreasonable.

When an attack lands, a **Judge agent** tries to patch the endorsement automatically — but only if the fix doesn't break any previous ruling. Every resolved case becomes a permanent constraint, a growing test suite the endorsement must satisfy.

If the Judge can't find a consistent fix — meaning any patch would contradict a prior decision — the case gets **escalated to you**. These escalated cases represent genuine tensions in the endorsement's goals, places where tightening one area necessarily loosens another.

The endorsement gets progressively more robust. But the real output isn't just the endorsement — it's the systematic discovery of edge cases and coverage tensions before they become real claims.

## How It Works

```
                    +-----------------+
                    |  Base Policy +  |
                    |  Endorsement    |
                    |  Goal           |
                    +--------+--------+
                             |
                             v
                    +--------+--------+
                    | Endorsement     |
                    | Drafter         |
                    | (drafts from    |
                    |  policy + goal) |
                    +--------+--------+
                             |
                             v
              +--------------+--------------+
              |                             |
    +---------v----------+      +-----------v--------+
    |    Gap Finder      |      |  Overreach Finder  |
    |  (endorsement      |      |  (endorsement      |
    |   doesn't achieve  |      |   removes intended |
    |   its goal)        |      |   coverage)        |
    +--------+-----------+      +-----------+--------+
              |                             |
              +-------------+---------------+
                            |
                            v
                   +--------+--------+
                   |     Judge       |
                   | (auto-resolve   |
                   |  or escalate)   |
                   +--------+--------+
                            |
                +-----------+-----------+
                |                       |
        +-------v-------+      +-------v--------+
        | Auto-resolved |      |  Escalated     |
        | (endorsement  |      |  to YOU        |
        |  updated,     |      |  (genuine      |
        |  case becomes |      |   coverage     |
        |  precedent)   |      |   tension)     |
        +---------------+      +----------------+
```

Each resolved case — whether by the Judge or by you — becomes binding precedent. The adversarial agents attack again, and the cycle repeats. Round after round, the endorsement tightens, and the cases that reach you get harder and more revealing.

## Setup

Requires Python 3.12+ and an Anthropic API key.

```bash
# Clone and install
git clone <repo-url>
cd loophole-insurance
uv sync

# Set your API key
export OLLAMA_API_KEY="your-key-here"
```

## Usage

Launch the interactive menu:
```bash
uv run python -m loophole.main
```

You'll see the main menu:

```
  1. Configure              LLM settings, loop parameters
  2. Select policy           Base policy to modify
  3. Select guidelines       Endorsement drafting guidelines
  4. Select template         Endorsement format template
  5. Start new session       Draft and stress-test an endorsement
  6. Previous sessions       Resume or review past sessions
  7. Exit
```

**Typical workflow:**
1. **Select policy** — choose a base policy from `templates/policies/`
2. **Select guidelines** (optional) — choose drafting guidelines, or use the built-in defaults
3. **Select template** (optional) — choose an endorsement format template
4. **Start new session** — enter your line of business and endorsement goal, then the adversarial loop begins

Each round of testing:
1. Both adversarial agents attack the current endorsement
2. The Judge processes each case (auto-resolve or escalate)
3. You see a summary and choose to continue, view the endorsement, or stop

When a case is escalated, you'll be prompted to make a decision. Your decision becomes a new constraint that the endorsement must respect going forward.

### Configuration

Use the **Configure** menu option to change LLM settings, temperatures, and loop parameters at runtime. You can save changes to `config.yaml` from within the menu.

```yaml
model:
  default: "minimax-m2.7:cloud"
  max_tokens: 8192

temperatures:
  drafter: 0.4             # Lower = more precise drafting
  gap_finder: 0.9          # Higher = more creative attacks
  overreach_finder: 0.9
  judge: 0.3               # Lower = more conservative judgments

loop:
  max_rounds: 10
  cases_per_agent: 3       # How many cases each attacker finds per round

session_dir: "sessions"
```

## Templates

Templates are organized in `templates/` with three subdirectories:

- **`templates/policies/`** — Base insurance policy documents. Add your own `.txt` or `.md` files here.
- **`templates/guidelines/`** — Endorsement drafting guidelines that define quality standards (burden of proof, surgical precision, contra proferentem, etc.). A default set is provided.
- **`templates/endorsements/`** — Structural format templates for endorsements (preamble, definitions, modifications, etc.). A standard template is provided.

## Tips for Best Results

- **Use relevant excerpts, not full policies.** A full cyber policy can be 20-40 pages. The policy text is included in every LLM prompt, so the most relevant sections (insuring agreements, definitions, exclusions) produce better results than the full document.
- **Be specific with goals.** "Add an exclusion" is too vague. "Add an exclusion for losses arising from state-sponsored cyber attacks while preserving coverage for attacks by non-state criminal actors" gives the drafter clear guardrails.
- **Engage with escalations.** The cases that reach you are the interesting ones — they reveal genuine tensions in what the endorsement is trying to achieve.

## Project Structure

```
loophole/
  main.py              Interactive menu and adversarial loop
  models.py            Data models (SessionState, Case, Endorsement)
  llm.py               LLM client (Ollama Cloud / OpenAI-compatible)
  prompts.py           All agent prompt templates
  session.py           Session persistence (JSON + markdown)
  visualize.py         HTML report generator
  template_browser.py  File browser for selecting templates
  agents/
    base.py            Base agent class
    drafter.py         Drafts and revises the endorsement
    gap_finder.py      Finds gaps where endorsement fails its goal
    overreach_finder.py Finds where endorsement removes intended coverage
    judge.py           Auto-resolves cases or escalates

templates/
  policies/            Base insurance policy documents
  guidelines/          Endorsement drafting guidelines
  endorsements/        Endorsement format templates
sessions/              One directory per session (auto-created)
config.yaml            Model and loop configuration
```
