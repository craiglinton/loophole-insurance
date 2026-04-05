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

### Start a new session

Interactive mode:
```bash
uv run python -m loophole.main
```

Or directly with a policy file and goal:
```bash
uv run python -m loophole.main new \
  --domain cyber \
  --policy examples/cyber_policy_excerpt.txt \
  --goal "Add an exclusion for state-sponsored cyber attacks"
```

You'll see the initial endorsement, then the adversarial loop begins. Each round:
1. Both adversarial agents attack the current endorsement
2. The Judge processes each case (auto-resolve or escalate)
3. You see a summary and choose to continue, view the endorsement, or stop

When a case is escalated, you'll be prompted to make a decision. Your decision becomes a new constraint that the endorsement must respect going forward.

### Resume a session

Sessions auto-save after every case. Pick up where you left off:
```bash
uv run python -m loophole.main resume
```

### Generate a visualization

After a session (or for any past session), generate an HTML report:
```bash
uv run python -m loophole.main visualize
```

This creates a `report.html` in the session directory with:
- The endorsement goal and base policy
- The initial endorsement
- A timeline of every adversarial case
- Git-style diffs showing how the endorsement changed after each case
- The final endorsement

### List sessions

```bash
uv run python -m loophole.main list
```

## Configuration

Edit `config.yaml` to tune the system:

```yaml
model:
  default: "claude-sonnet-4-20250514"   # Which Claude model to use
  max_tokens: 4096

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

## Tips for Best Results

- **Pass relevant excerpts, not full policies.** A full cyber policy can be 20-40 pages. The policy text is included in every LLM prompt, so passing the most relevant sections (insuring agreements, definitions, exclusions) produces better results than overwhelming the model with the full document.
- **Be specific with goals.** "Add an exclusion" is too vague. "Add an exclusion for losses arising from state-sponsored cyber attacks while preserving coverage for attacks by non-state criminal actors" gives the drafter clear guardrails.
- **Engage with escalations.** The cases that reach you are the interesting ones — they reveal genuine tensions in what the endorsement is trying to achieve.

See `examples/cyber_policy_excerpt.txt` for a sample base policy.

## Project Structure

```
loophole/
  main.py              CLI and main adversarial loop
  models.py            Data models (SessionState, Case, Endorsement)
  llm.py               Anthropic SDK wrapper
  prompts.py           All agent prompt templates
  session.py           Session persistence (JSON + markdown)
  visualize.py         HTML report generator
  agents/
    base.py            Base agent class
    drafter.py         Drafts and revises the endorsement
    gap_finder.py      Finds gaps where endorsement fails its goal
    overreach_finder.py Finds where endorsement removes intended coverage
    judge.py           Auto-resolves cases or escalates

sessions/              One directory per session (auto-created)
examples/              Example base policies
config.yaml            Model and loop configuration
```
