# How it answers

What happens between a question and an answer, and a first look at how well it works.

## Loading the Act

`python -m chapter_and_verse.ingest ukpga/1996/18` downloads the Employment Rights Act
1996 from legislation.gov.uk as one XML document, at its latest revised version. The Act
has 435 sections. 25 are repealed and left out, so 410 are stored, each with its number,
title, text, address on legislation.gov.uk and the date from which that text is in force.
For the version loaded, that date is 30 October 2026.

Each section is split into chunks of whole lines, up to 200 words, which keeps a chunk
under the model's limit of 512 tokens. The section title goes in front of each chunk, so a
chunk from the middle of a section keeps its subject. Each chunk then gets a vector of 384
numbers from `BAAI/bge-small-en-v1.5`, a small model that runs on the CPU. The Act gives
887 chunks. Loading it again replaces it in one transaction.

## Finding sections

The question gets a vector from the same model. Postgres, with the pgvector extension,
compares it with every chunk by cosine distance and returns the five sections whose
closest chunk is nearest. There is no index. With under a thousand chunks, an exact search
takes 1 to 4 milliseconds once the chunks are in memory, and unlike an approximate index
it never skips a closer chunk.

The search uses chunks and the answer uses whole sections. A chunk finds the place, and
the model reads the section around it.

## Answering

Claude gets the five sections, then the question. It is told to answer only from them, to
cite the section after each claim, and to say so and cite nothing when they do not answer
the question. The reply carries the answer and the sections it was given. Both are
stored, with the date each section's text is in force from. The model is set by
`CLAUDE_MODEL` in the [settings](../README.md#settings).

## A first look

Measured on 21 November 2026 with `claude-haiku-4-5`. Twelve questions, each with the
section a reader of the Act would expect, and two questions the Act does not answer.

| Question | Expected | In the five | Answer |
| --- | --- | --- | --- |
| How much notice must my employer give me before ending my job? | s. 86 | yes | right |
| How long must I work before I can claim unfair dismissal? | s. 108 | no | refused |
| What must a written statement of employment particulars contain? | s. 1 | yes | right |
| How is a redundancy payment calculated? | s. 162 | yes | right |
| Can I ask my employer for flexible working? | s. 80F | yes | right |
| Can I take time off to care for a dependant in an emergency? | s. 57A | yes | right |
| What counts as a protected disclosure by a whistleblower? | s. 43B | yes | right |
| Do I have a right to an itemised pay statement? | s. 8 | yes | right |
| Who counts as an employee under the Act? | s. 230 | yes | right |
| When is a dismissal for redundancy? | s. 139 | yes | right |
| Can my employer take money out of my wages? | s. 13 | no | refused |
| What reasons make a dismissal fair? | s. 98 | yes | right |
| What is the speed limit on a motorway? | none | | refused |
| How much is the national minimum wage? | none | | refused |

The expected section was in the five returned for 10 of 12. The two misses:

- s. 108 sets the two years of service for unfair dismissal, but it never says "unfair". It
  names the right as "section 94". It ranked 21st, and s. 111, on complaints to a
  tribunal, came first.
- s. 13 was not in the top 50. The question says "take money out of my wages", and the
  Act says "deductions".

Five sections more would not fix either miss. Questions in everyday words miss sections
written in legal words, so a keyword search next to the vector search is the next thing to
test.

Of the twelve answers, 10 were right and cited only sections they were given. In the two
misses the model said it could not answer and invented nothing, but one of those refusals
still cited a section. Both questions with no answer in the Act were refused. No answer
cited a section outside its sources. Answers took 1.2 to 4.1 seconds, median 1.9.

Twelve questions are a first look, not an evaluation.

## What is not there yet

- Nothing checks that a cited section exists or says what the answer claims.
- The service does not refuse on its own. Only the model's instructions make it say no,
  and a refusal can still carry a citation.
- The prompt does not name the Act. In one refusal the model suggested looking in the
  Employment Rights Act 1996, the Act it was reading.
- One Act, at one version. Earlier versions, and the parts of the UK a section applies
  to, are not stored.
- No evaluation set and no gate in CI.
