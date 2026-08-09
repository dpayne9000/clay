## Example Uses

### Cover Letter
Job title + company + skills → AI draft → your review → polished final letter.
```bash
python clay.py run workflows/templates/content/cover-letter.json
```
```
Job title you are applying for: Senior Backend Engineer
Company name: Stripe
Your top 3 relevant skills (comma-separated): Node.js, PostgreSQL, system design
One sentence describing your most relevant experience: Built a payments API handling 2M transactions/month

→ [AI drafts letter]

Review the draft. Enter revision notes, or press Enter to accept: Make it punchier

→ [AI revises and returns final letter]
```

---

### Meeting Summary & Action Items
Paste raw notes → structured summary → your corrections → formatted action items with owners.
```bash
python clay.py run workflows/templates/business/meeting-summary.json
```
```
Meeting name or topic: API Gateway Migration
Attendees (comma-separated names): Sarah, Dev, Priya
Paste your meeting notes:
We agreed to migrate from Kong to AWS API Gateway by Q2. Dev leads.
Sarah flagged staging needs updating first. Priya to handle comms.

→ SUMMARY / KEY DECISIONS / OPEN QUESTIONS

Any corrections or additions? (press Enter to skip): Priya's deadline is before staging starts

→ ACTION ITEMS
   1. Dev   — Lead API Gateway migration    — Due: End of Q2
   2. Sarah — Update staging environment   — Due: Before migration
   3. Priya — Communicate changes to teams — Due: Before staging
```

---

### Job Description
Role details → requirements → AI job ad → your edits → final version.
```bash
python clay.py run workflows/templates/business/job-description.json
```
```
Job title: Senior Backend Engineer
Team or department: Platform
Location and work type: Remote
Seniority level: Senior
Main responsibilities: design APIs, maintain infrastructure, mentor juniors
Required skills: Node.js, PostgreSQL, Docker, AWS
Nice-to-have skills (press Enter to skip): Kafka, Terraform

→ [AI writes job description]

Review the job description. Enter edits or press Enter to finalise:
Add a note that visa sponsorship is not available

→ [AI applies note and returns final JD]
```

---

### Project Proposal
Project details + scope → full formal proposal → approve or revise.
```bash
python clay.py run workflows/templates/business/project-proposal.json
```
```
Project name: Customer Portal Redesign
Client or stakeholder name: NorthBridge Financial
Estimated budget: £55,000
Estimated timeline: 12 weeks
Main objective in one sentence: Reduce support calls by improving self-service
Key deliverables: UX audit, design system, rebuilt frontend, user testing
Anything explicitly out of scope (press Enter to skip): Backend API changes, mobile app

→ [AI writes full proposal]

Review the proposal. Type APPROVE or enter changes needed:
Add a risk section about client feedback turnaround

→ [AI adds risk section and returns final proposal]
```

---

### Blog Post
Topic + audience + angle → AI outline → adjust it → full draft → polish for publish.
```bash
./clay.py run workflows/templates/content/blog-post.json
```
```
Blog post topic: why most API documentation fails
Target audience: developers
Tone: conversational
What angle should this post take?: Good docs are a product decision, not a writing task

→ [AI generates outline]

Review the outline. Enter changes or press Enter to continue: (Enter)

→ [AI writes 600-800 word draft]

Read the draft. Enter revision notes or press Enter to publish as-is: The ending feels weak

→ [AI returns polished final post]
```

---

### Incident Report
Incident details + timeline → blameless postmortem → fill in owners and dates.
```bash
python clay.py run workflows/templates/business/incident-report.json
```
```
Incident title: API Outage — 7 March 2026
Severity: P1
What was affected?: All users — login unavailable
Duration of the incident: 47 minutes
What happened?: Deploy introduced a connection leak in auth service
How was it detected?: PagerDuty alert on login error rate
How was it resolved?: Rolled back the deploy
Root cause: Missing connection cleanup in error handling path

→ [AI writes full postmortem with timeline, RCA, and action items]

Review the report. Fill in owners/dates, or press Enter to skip:
Action item 1 is owned by Priya, due March 14th

→ [AI updates action items with owner and deadline]
```

---

### Research Document Generator
Full 4-level nested workflow: intake → AI research → AI draft → AI critique + human gate → final document. The most complex workflow — run this when you want to see nested workflows in action.
```bash
python clay.py run workflows/templates/research/main.json
```
```
What topic should this document cover?: the rise of remote work
What type of document?: executive briefing
Who is the target audience?: corporate real estate investors
Research depth — quick / standard / comprehensive: comprehensive

→ [research pipeline: 5 automated AI steps → research brief]
→ [draft pipeline: 6 automated AI steps → full document]
→ [review pipeline: AI critique generated]

=== DRAFT ===
THE RISE OF REMOTE WORK: IMPLICATIONS FOR COMMERCIAL REAL ESTATE
...

=== AI CRITIQUE ===
STRENGTHS: Data is specific and well-sourced...
WEAKNESSES: Background section over-explains pre-pandemic context...

Enter revision notes, or type APPROVE to accept:
> Cut background by 30%, add interest rate context

→ [AI applies revisions → final polished document]
```
Total AI calls: ~12 automated. Human interactions: 5 (4 intake + 1 approval).

---

## Creating Your Own Workflow

**Interactively:**
```bash
python clay.py create my-workflow
```
Prompts you for step names and walks through adding actions to each step. Saves to `my-workflow.json`.

**By hand:** copy any file from `workflows/` and edit the JSON. The interactive builder is good for structure; editing JSON directly is faster for tuning prompts.

See `WORKFLOWS.md` for a full technical reference — action types, data flow, prompt substitution, and annotated workflow structure.