# For manufacturers

This guide is for an appliance manufacturer, or a developer working for one, who
wants to try FixIt on **its own manuals** and, eventually, ship its own support
add-on for a voice assistant.

Read this first: FixIt is a hackathon project (release 0.2.0), not a finished
product or a service. It works end to end on seven real manuals (error codes from
five of them, troubleshooting-table rows from two) and a simulated assistant, and
this page says plainly what that does and does not cover. The code is
MIT-licensed, so you can run, change and host it yourself.

## What FixIt is, and what it does not do

FixIt is a small server (an
[MCP](https://modelcontextprotocol.io) server, spoken to over HTTP) that lets a
voice assistant answer appliance questions from **cited facts extracted from the
manufacturer's own manual**. It has six tools:

| Tool | What it does |
|---|---|
| `diagnose_error` | Looks up an error code: meaning, likely causes, repair steps, parts, safety warnings, each cited to a manual page. An unknown code is `not_found` with the nearest known codes, never an invented answer. |
| `diagnose_symptom` | For a described problem with no code ("it won't drain", "the fridge keeps beeping"), returns the manual's own troubleshooting rows (the problem, possible causes, what to do), cited to a page. Keyword matching only; it says `not_found` rather than guess. |
| `check_warranty` | Compares the *recorded* warranty end date with today. It never says what a warranty covers or whether a repair would be covered. |
| `list_my_appliances`, `add_appliance`, `remove_appliance` | A household's registered appliances, linked to the right manual by brand and model. |

What matters most about how it works:

- **The live server makes no model calls.** Not in any tool, not ever. A tool call is
  a lookup in memory. The assistant (the thing that talks to the customer) writes
  the words, from the structured results the tools return. This is a design rule,
  tested, and the reason tool calls are fast.
- **All AI work is offline**, ahead of time, when a manual is added: reading the
  PDF and extracting records. Those records are checked, committed to the
  repository as two data files, and baked into the server's container image.
- **It is not a replacement for the manual or for service.** It returns what the
  manual says. It does not diagnose from first principles, estimate repair costs,
  judge whether something is safe (beyond a warning the manual itself lists),
  or say what a warranty covers.

It does not (yet) connect to the real Alexa+; see
[what is not done yet](#what-is-not-done-yet).

## From a manual PDF to cited records

Everything below is a real command in this repository. You need Python 3.12 and
[`uv`](https://docs.astral.sh/uv/); `make` runs the steps.

```bash
git clone https://github.com/sadishihab/fixit-mcp.git && cd fixit-mcp
uv sync
make test                 # the whole suite passes before you change anything
```

### 1. Error codes: `make add-manual`

```bash
make add-manual ID=acme-x100-oven BRAND=Acme MODEL=X100 TYPE=oven \
  URL=https://example.com/x100-owners-manual.pdf \
  NOTE="Acme's own support page; free download, no login."
make add-manual ... DRY_RUN=1     # check the PDF first, change nothing
```

One command runs the whole chain, printing each step:

1. validates the arguments (a duplicate id or brand+model is refused);
2. downloads the PDF and checks it really is one;
3. **content check**: the PDF must contain the model number (or its series stem) and
   a troubleshooting or error-code keyword. This exists because a filename or a
   search title proves nothing: a real, valid PDF turned out to be a three-page spec
   sheet;
4. appends the entry to `data/manuals/manifest.yaml` (a non-empty `NOTE` saying
   where the URL came from is required);
5. parses the PDF into section-aware chunks, repairing broken font encodings;
6. extracts records: with `FIXIT_EXTRACTOR=stub` (the default, no AWS) it finds
   code strings only; with `FIXIT_EXTRACTOR=bedrock` it calls Claude on Amazon
   Bedrock, validates every record against a schema, retries a bounded number of
   times, and returns nothing rather than guess. It prints a token and cost
   estimate first and asks you to type `yes`;
7. merges the records into `data/index/error_codes.json`, replacing only that
   manual's records. Re-running is safe.

The download is a plain HTTP GET with no credentials. A manual that is not on a URL
this machine can reach has to be hosted somewhere reachable first; that path is not
tested.

### 2. Symptom tables: `make extract-symptoms`

Many manuals also have a "Problem / Possible Causes / What To Do" table. These are
extracted separately, with **Amazon Nova Pro only** (any other model id is refused):

```bash
make extract-symptoms DRY_RUN=1                       # read the tables, print row counts and the cost estimate
make extract-symptoms MANUAL=acme-x100-oven MAX_COST=0.5   # asks before spending; hard cap in USD
```

It reads each table from the PDF's geometry so rows stay aligned, has the model copy
each row verbatim, and then **checks the answer before keeping any of it**:

- the number of rows must match the table (an empty or short answer is retried);
- for every row, the extracted strings, joined, must equal the source cell exactly
  (so an invented or dropped word fails);
- footnote markers must link to the right footnote;
- a row that ends mid-sentence is flagged;
- if any table of a manual fails after the bounded retries, **none of that manual's
  rows are written**.

Accepted answers are cached and re-checked on every read. Only manuals with a ruled,
three-column table of that shape are supported today (the GE range's table is not,
see below). Open the rendered pages and spot-check a few rows before committing.

### 3. Check, review, commit

```bash
make validate-manifest    # fields, unique ids, notes, and every record points at a manifest entry
make test                 # includes the manifest check
```

Then review the diff and commit the manifest and the two index files
(`data/index/error_codes.json`, `data/index/symptoms.json`). **Never commit the
PDFs** (they are gitignored). A new manual reaches a deployed server only after you
rebuild the image and update the runtime.

The audit above is strongest for symptom tables. For error codes the safeguards
are the schema, the retries, the "return nothing rather than guess" rule and your
own review. Extraction is not perfect: `FRICTION_LOG.md` records the real failure
modes found so far (broken font encodings, tables the parser fragments, a
one-character glyph error), and each was caught by checking real output, not
assumed away. Plan to review.

## What you own and control

- **Your manuals and your data.** You run it on your own PDFs, in your own copy of
  the repository. The extracted records are plain JSON files in that copy; nothing is
  sent to any service run by this project.
- **Every record cites its manual and page**, and the manifest records where each
  manual came from. The repository stores only extracted records and metadata, not
  the PDFs, and the records are facts (codes, meanings, steps) rather than
  reproductions of the manual's text.
- **Removal on request.** For the manuals already in this repository (GE, Bosch, LG,
  Samsung, taken from their public downloads), a manufacturer that wants its records
  removed can ask, and the maintainer will remove them. Your own fork is yours to
  edit.
- **Terms of use are your call.** Records are committed and shipped in the container
  image, so before adding a manual make sure redistributing extracted facts, cited to
  the manual, is acceptable under its terms. That is a question for your own counsel;
  nothing here is legal advice.

## Deploying it

The server is one container that serves `0.0.0.0:8000/mcp` over Streamable HTTP, in
stateless mode. No settings need to change for that.

```bash
make docker-build        # linux/arm64, the AgentCore Runtime target
make docker-run          # serves http://localhost:8000/mcp
make docker-smoke        # end-to-end MCP checks against the running container
```

**On Amazon Bedrock AgentCore Runtime** (the tested deployment): `make docker-push`
pushes the exact image you tested to ECR, and `make deploy-runtime` creates or
updates the runtime pinned to that image's digest; `make runtime-smoke` checks the
deployed runtime, and `make teardown-runtime` deletes it and stops its compute
charges. IAM policy templates are in `deploy/iam/` (`make iam-policies` fills in
your account's values; nothing with an account id is committed). The README's
"Deploying to AgentCore Runtime" section has the full sequence.

**On another host.** Anything that runs a container and can serve HTTP should work:
build for your CPU (`DOCKER_PLATFORM=linux/amd64 make docker-build`) and put it
behind TLS. Only local Docker and AgentCore Runtime have been tested. Two things
differ:

- **Household storage.** Where appliances are kept is behind a three-method
  interface (`ApplianceRepository`: list, add, remove). Three implementations exist:
  in-memory, SQLite (a file inside the container, fine for one instance with a
  volume) and Amazon Bedrock AgentCore Memory. `FIXIT_REPOSITORY_BACKEND` chooses
  among them. To use your own database, implement the three methods and select it in
  `src/fixit_mcp/server.py`; a small, contained code change, not a setting.
- **Authentication.** See below: there is none yet.

## How a customer's appliances are kept

A household is identified by an id the caller supplies. `add_appliance` stores the
brand, model and type (and optionally a purchase and warranty date) and links the
appliance to a manual by matching brand and model; if no manual matches it still
saves the appliance and says diagnosis coverage will be limited. On AgentCore Runtime
each household is an actor in **AgentCore Memory** and each appliance is one event,
with no model-driven extraction. Events **expire after at most 365 days**. The server
never seeds data at runtime.

Two things to weigh honestly: the household id is **not authenticated** (any caller
that can reach the server can read or change any household), and no per-customer
account linking is built. Before this holds real customers' data it needs OAuth
account linking in front of it, which the real Alexa+ requires anyway.

## The grounding eval, and why it exists

A server that never calls a model can still be made to say untrue things by the
assistant that reads its results. So the project measures that. `make eval` runs
about 70 scripted conversations through the demo against the local server: found and
unknown codes, described problems, safety questions where the manual lists no
warning, warranty questions, and adversarial follow-ups ("how much will the repair
cost?", "is it dangerous?", "is it covered?"). Each reply is checked
deterministically (right tool, required or forbidden phrases) and by a second model
that sees only the tool results and the reply and lists any claim they do not
support.

```bash
make run                          # one terminal: the local server
make eval                         # another: needs AWS credentials for Bedrock
uv run --group demo python scripts/run_eval.py --estimate-only   # cost first
```

It is evidence, not proof. The judge is a model and can be wrong both ways, and the
eval cannot check that the tool results themselves are right (that is the extraction
audit's job). Real results so far: the last full run recorded (63 cases, one run)
passed 62; the six symptom cases were run once on Nova Pro as both assistant and judge
and **3 of 6 passed**, with the judge missing an invented "normal" that a plain text
check caught, and the assistant prompt was changed afterwards and those cases have not
been re-run. See [`CONTRIBUTING.md`](../CONTRIBUTING.md#how-we-measure-grounding) and
`FRICTION_LOG.md`.

## Costs, stated honestly

All figures are what this project measured or was told, at the time of writing;
prices change, so check AWS's pages.

- **Extraction is cents per manual.** Symptom extraction with Nova Pro for the two GE
  manuals (114 rows, 7 table calls plus retries) cost about **$0.10** in total, using
  list prices the code assumes. Error-code extraction with Claude on Bedrock cost
  about **$0.14** for one manual's code table in the real run recorded (LG washer),
  and every run prints an estimate first and asks before spending. A month of
  extraction, demo and eval runs on Claude came to the order of **ten dollars**,
  including tax.
- **Claude on Bedrock is billed through AWS Marketplace.** The hackathon organizers
  confirmed it is sold by Anthropic through the Marketplace and is **not covered by
  the hackathon AWS credit**, and that first-party models such as Amazon Nova are.
  That is a hackathon-credit fact; outside the hackathon, both are ordinary AWS usage
  and you pay for both. This is why symptom extraction uses Nova only, and refuses
  other models.
- **Running the server** on AgentCore Runtime is ordinary compute pricing; this
  project has not measured a monthly figure. `make teardown-runtime` stops it
  (the ECR image is about a cent a month). The CloudWatch setup is designed to stay
  within the free tier.
- **The eval** costs real money because it calls a judge model; the script prints an
  estimate and refuses to start above `--max-cost`.

## What is not done yet

- **No connection to the real Alexa+.** The Alexa+ developer tools (account linking,
  the local inspector, add-on submission) are not available to hackathon participants,
  so the real client has never called this server. The demo is a simulation of it.
  Whether the visual cards render on a real Alexa+ device is unverified.
- **No authentication or account linking.** The deployed server accepts only
  AWS-signed requests (IAM SigV4). OAuth 2.1 account linking, which a real add-on
  needs, is not built.
- **No parts ordering and no maintenance scheduling.**
- **Symptom coverage is two manuals.** Only the GE refrigerator and washer have
  symptom rows (114). The GE range's troubleshooting table is unruled and needs its
  own reader. Error codes cover five of the seven manuals in the repository.
- **Symptom matching is keyword-based and can miss things.** On the project's own
  bank of invented phrasings it got 43 of 47 right with no wrong answers, but on
  held-out phrasings it found only 4 of 10, and it has one known wrong answer. It says
  "not found" rather than guess. The phrasings were written by the maintainer, not
  recorded from customers.
- **Latency is not confirmed inside the region.** Warm calls measured about 570 ms
  from Dhaka, of which about 320 ms is network; a brand-new session takes about 5
  seconds. The 500 ms assistant budget is not yet confirmed from an in-region client.
- **Extraction needs review.** See above.

## A sensible way to evaluate it

1. `make try-it` and `make test`, to see it work with no AWS account.
2. Add **one** of your manuals with `make add-manual ... DRY_RUN=1`, then without.
3. Review the records against the PDF, page by page.
4. `make run`, then call the tools from the MCP Inspector (`make inspector`).
5. Only then decide whether to deploy, and what authentication you would need.

Architecture: [`docs/architecture.md`](architecture.md). Requirements checklist
against the Alexa+ MCP Toolkit: [`docs/alexa-plus-requirements.md`](alexa-plus-requirements.md).
Contributing and the add-a-manual rules: [`CONTRIBUTING.md`](../CONTRIBUTING.md).
