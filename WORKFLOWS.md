# clay Workflow Guide

Workflows are JSON files that define a sequence of **steps**, each containing one or more **actions**. The CLI executes them in order, passing outputs from earlier steps into later ones via `includedData`.

## Commands

```bash
cd clay
source .venv/bin/activate
export GOPHER_URL=http://127.0.0.1:8080     # optional; local OpenAI-compatible model server (default)

python clay.py run   <workflow.json>    # execute a workflow
python clay.py create <name>            # build a workflow interactively
python clay.py dryrun <workflow.json>   # validate without executing
```

---

## How Data Flows

Each action that returns a result stores it in `previous_data` under its `id`:

```
step 1: humanDecision  id="job_title"   → previous_data["job_title"] = "Engineer"
step 2: scramda2       includedData=["job_title"]
                       → handler receives {"job_title": "Engineer"}
                       → resolves prompt: "Write a letter for a {job_title}"
                                      → "Write a letter for a Engineer"
```

### Prompt substitution in `scramda2_actions.py`

The handler resolves `{placeholder}` tokens in the prompt before sending to the AI service. Missing keys are left in place rather than crashing:

```python
class SafeMap(dict):
    def __missing__(self, key):
        return f'{{{key}}}'   # unresolved → leave as {key}

resolved_prompt = prompt.format_map(SafeMap(previous_data))
```

**Without substitution** — Ollama receives the raw template and must infer what `{job_title}` means from the examples. Works, but unreliable.

**With substitution** — Ollama receives `"Write a letter for a Senior Engineer at Stripe"`. Much more accurate.

---

## Action Types

| Type | What it does |
|------|-------------|
| `humanDecision` | Pauses and prompts the user for input via `input()` |
| `scramda2` | POSTs to local Ollama AI service; returns generated text |
| `API` | Makes an HTTP request to an external endpoint |
| `mongo` | Reads from or writes to MongoDB |
| `python` | Executes an inline Python expression |
| `transformData` | Reshapes data between steps |
| `report` | Renders a report from a template |

---

## Workflow File Structure

```json
{
  "workflow": {
    "steps": ["stepOne", "stepTwo", "stepThree"]
  },
  "actionSets": {
    "stepOne": [
      {
        "id": "result_key",
        "type": "humanDecision | scramda2 | API | ...",
        "prompt": "Text shown to user or sent to AI",
        "examples": [{ "question": "...", "answer": "..." }],
        "includedData": ["id_from_previous_step"]
      }
    ],
    "stepTwo": [ ... ]
  }
}
```

- `id` — key used to store this action's output in `previous_data`
- `includedData` — optional list of accumulated context values to pass into
  this action. When omitted, the action receives the complete accumulated
  context. Use `alias=parent_id.child_id` to select and rename a value from a
  workflow or loop result.
- `examples` — few-shot training examples for `scramda2` actions

---

## Example 1 — Cover Letter Generator

**Steps:** collect inputs → AI draft → human review → AI finalise

```json
{
  "workflow": {
    "steps": ["gatherInputs", "draftLetter", "humanReview", "finalise"]
  },
  "actionSets": {
    "gatherInputs": [
      {
        "id": "job_title",
        "type": "humanDecision",
        "prompt": "Enter the job title you are applying for"
      },
      {
        "id": "company",
        "type": "humanDecision",
        "prompt": "Enter the company name"
      },
      {
        "id": "skills",
        "type": "humanDecision",
        "prompt": "List your top 3 relevant skills (comma-separated)"
      }
    ],
    "draftLetter": [
      {
        "id": "draft",
        "type": "scramda2",
        "prompt": "Write a professional cover letter for a {job_title} position at {company}. The applicant has these skills: {skills}. Keep it under 300 words.",
        "examples": [
          {
            "question": "Write a cover letter for a Software Engineer at Acme. Skills: TypeScript, Node.js, MongoDB.",
            "answer": "Dear Hiring Manager,\n\nI am writing to express my interest in the Software Engineer position at Acme. With strong experience in TypeScript, Node.js, and MongoDB I have built and maintained scalable APIs serving thousands of users. I would welcome the chance to bring this to Acme.\n\nYours sincerely,\n[Name]"
          }
        ],
        "includedData": ["job_title", "company", "skills"]
      }
    ],
    "humanReview": [
      {
        "id": "feedback",
        "type": "humanDecision",
        "prompt": "Review the draft. Enter revisions (or press Enter to accept)"
      }
    ],
    "finalise": [
      {
        "id": "final",
        "type": "scramda2",
        "prompt": "Revise this cover letter based on the feedback. If feedback is empty return the draft unchanged.\n\nFeedback: {feedback}\n\nDraft:\n{draft}",
        "examples": [
          {
            "question": "Feedback: Make it shorter. Draft: Dear Hiring Manager, I am writing to express my interest...",
            "answer": "Dear Hiring Manager,\n\nWith strong TypeScript and Node.js skills I am confident I can contribute to Acme from day one. Thank you for your consideration.\n\nYours sincerely,\n[Name]"
          }
        ],
        "includedData": ["draft", "feedback"]
      }
    ]
  }
}
```

**Terminal session:**

```
$ python clay.py run cover-letter.json

Enter the job title you are applying for: Senior Backend Engineer
Enter the company name: Stripe
List your top 3 relevant skills (comma-separated): Node.js, PostgreSQL, system design

[scramda2] Generating draft...
→ "Dear Hiring Manager, I am writing to express my interest in the Senior Backend
   Engineer position at Stripe. With expertise in Node.js, PostgreSQL and system
   design I have architected APIs processing over 1M requests per day..."

Review the draft. Enter revisions (or press Enter to accept):
Add a line about my open source contributions

[scramda2] Finalising...
→ "Dear Hiring Manager, I am excited to apply for the Senior Backend Engineer role
   at Stripe. In addition to my Node.js and PostgreSQL expertise, I actively
   contribute to open source projects including [project]. I would love to bring
   this energy to Stripe..."
```

---

## Example 2 — Meeting Summary & Action Items

**Steps:** collect notes → AI summary → human corrections → AI action items

```json
{
  "workflow": {
    "steps": ["transcriptInput", "aiSummary", "humanConfirm", "actionItems"]
  },
  "actionSets": {
    "transcriptInput": [
      {
        "id": "meeting_name",
        "type": "humanDecision",
        "prompt": "Enter the meeting name or topic"
      },
      {
        "id": "attendees",
        "type": "humanDecision",
        "prompt": "List attendees (comma-separated)"
      },
      {
        "id": "transcript",
        "type": "humanDecision",
        "prompt": "Paste meeting notes or transcript"
      }
    ],
    "aiSummary": [
      {
        "id": "summary",
        "type": "scramda2",
        "prompt": "Summarise this meeting called {meeting_name} attended by {attendees}. Provide: a 2-3 sentence overview, key decisions, and open questions.\n\nNotes:\n{transcript}",
        "examples": [
          {
            "question": "Summarise Q1 Planning attended by Alice, Bob. Notes: Discussed roadmap. Alice wants mobile first. Bob flagged budget concerns. No date set.",
            "answer": "SUMMARY\nThe team reviewed Q1 priorities focusing on mobile development. Budget constraints were flagged as a risk requiring further discussion.\n\nKEY DECISIONS\n- Mobile to be Q1 priority\n\nOPEN QUESTIONS\n1. What is the available mobile budget?\n2. When is the next planning session?"
          }
        ],
        "includedData": ["meeting_name", "attendees", "transcript"]
      }
    ],
    "humanConfirm": [
      {
        "id": "corrections",
        "type": "humanDecision",
        "prompt": "Review the summary. Enter corrections or additions (or press Enter to continue)"
      }
    ],
    "actionItems": [
      {
        "id": "actions",
        "type": "scramda2",
        "prompt": "From this meeting summary and corrections, extract a clear action item list. Format: [Owner] - [Task] - [Due: timeframe or TBD].\n\nSummary:\n{summary}\n\nCorrections:\n{corrections}",
        "examples": [
          {
            "question": "Summary: Charlie to spike React Native. Budget review needed. Corrections: Alice owns budget review, due end of month.",
            "answer": "ACTION ITEMS\n1. Charlie - React Native feasibility spike - Due: TBD\n2. Alice - Q1 budget review - Due: End of month"
          }
        ],
        "includedData": ["summary", "corrections"]
      }
    ]
  }
}
```

**Terminal session:**

```
$ python clay.py run meeting-summary.json

Enter the meeting name or topic: API Gateway Migration
List attendees (comma-separated): Sarah, Dev, Priya
Paste meeting notes or transcript:
We agreed to migrate from Kong to AWS API Gateway by end of Q2.
Dev will lead the migration. Sarah flagged that the staging environment
needs updating first. Priya to handle comms to affected teams. No budget
concerns raised.

[scramda2] Generating summary...
→ "SUMMARY
   The team agreed to migrate from Kong to AWS API Gateway with a Q2 deadline.
   Dev will lead the technical work with Sarah handling a prerequisite staging
   update and Priya coordinating stakeholder communications.

   KEY DECISIONS
   - Migrate to AWS API Gateway by end of Q2
   - Dev leads migration effort

   OPEN QUESTIONS
   1. What is the exact Q2 deadline date?"

Review the summary. Enter corrections or additions (or press Enter to continue):
Add that Priya's comms deadline is before the staging work starts

[scramda2] Extracting action items...
→ "ACTION ITEMS
   1. Dev    - Lead API Gateway migration         - Due: End of Q2
   2. Sarah  - Update staging environment         - Due: Before migration start
   3. Priya  - Communicate changes to teams       - Due: Before staging work begins"
```

---

## Example 3 — Minimal Single-Step AI Prompt (no human interaction)

The simplest possible workflow — one step, one AI action, no human input:

```json
{
  "workflow": {
    "steps": ["generate"]
  },
  "actionSets": {
    "generate": [
      {
        "id": "output",
        "type": "scramda2",
        "prompt": "Write a one-paragraph executive summary of the benefits of microservices architecture for a non-technical audience.",
        "examples": [
          {
            "question": "Write a one-paragraph executive summary of the benefits of containerisation for a non-technical audience.",
            "answer": "Containerisation packages software so it runs identically on any computer, whether a developer's laptop or a production server. This eliminates the classic 'it works on my machine' problem, speeds up deployments, and makes it easy to scale individual parts of an application up or down based on demand — saving both time and infrastructure cost."
          }
        ]
      }
    ]
  }
}
```

```
$ python clay.py run exec-summary.json

[scramda2] Generating...
→ "Microservices architecture breaks a large application into smaller,
   independent services that each handle one specific job. Instead of
   one enormous system where a single bug can bring everything down,
   each piece can be updated, fixed, or scaled on its own — meaning
   faster releases, fewer outages, and teams that can work in parallel
   without getting in each other's way."
```

---

## Example 4 — Human Gate (approve before continuing)

A `humanDecision` step used as an approval gate. The workflow continues regardless of what the user types — but the value is available to downstream steps, so you can use it as context for a final AI action.

```json
{
  "workflow": {
    "steps": ["draft", "approvalGate", "publish"]
  },
  "actionSets": {
    "draft": [
      {
        "id": "topic",
        "type": "humanDecision",
        "prompt": "Enter the blog post topic"
      },
      {
        "id": "draft_post",
        "type": "scramda2",
        "prompt": "Write a short blog post (3 paragraphs) about {topic} for a developer audience.",
        "examples": [
          {
            "question": "Write a short blog post about rate limiting for a developer audience.",
            "answer": "Rate limiting is one of those things you don't think about until your API is on fire...\n\nThe most common approach is the token bucket algorithm...\n\nImplementing rate limiting early, even crudely, saves pain later..."
          }
        ],
        "includedData": ["topic"]
      }
    ],
    "approvalGate": [
      {
        "id": "approved",
        "type": "humanDecision",
        "prompt": "Type APPROVE to publish, or enter revision notes"
      }
    ],
    "publish": [
      {
        "id": "final_post",
        "type": "scramda2",
        "prompt": "Finalise this blog post applying any revision notes. If the note is APPROVE, return it unchanged.\n\nNotes: {approved}\n\nDraft:\n{draft_post}",
        "examples": [
          {
            "question": "Notes: APPROVE. Draft: Rate limiting is one of those things...",
            "answer": "Rate limiting is one of those things..."
          }
        ],
        "includedData": ["draft_post", "approved"]
      }
    ]
  }
}
```

---

## Tips

**Chain outputs deliberately.** Give each action a meaningful `id` — it becomes the key you reference in `includedData` downstream.

Nested workflow and loop results remain dictionaries under their action ids.
Reference a child action with a dot path:

```json
{
  "includedData": [
    "summary=research_workflow.final",
    "review=review_loop.review"
  ]
}
```

Loop `continueKey` names the final-iteration key used to decide whether another
iteration runs. Loop `outputKey` only selects a value previewed in the run log;
it does not change the dictionary stored under the loop id. Workflow
`outputKey` is accepted for compatibility but currently ignored.

`autoContext` is recursive. A nested workflow or loop iteration inherits its
parent's instructions and appends its own `autoContext`, if present. Engine
globals (`__config__`, `__schema__`, and `__workflow_template__`) are reseeded
at nested boundaries even when a workflow or loop action filters ordinary
inputs with `includedData`.

**Keep examples tight.** One good example per `scramda2` action is usually enough. The example teaches format and tone; the substituted prompt provides the content.

**Human steps as checkpoints.** Place a `humanDecision` after any AI step where quality matters. The user's input (corrections, approval, extra context) feeds directly into the next AI call.

**Test the model server in isolation first.** The Gopher adapter talks to an OpenAI-compatible endpoint (e.g. `llama.cpp`'s `llama-server`). Hit it directly with curl before wiring a full workflow:

```bash
curl -s -X POST "$GOPHER_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "unsloth/Qwen3-0.6B-GGUF:Q6_K",
    "messages": [
      {"role": "user", "content": "Summarise climate change for a general audience."}
    ]
  }' | python3 -m json.tool
```
