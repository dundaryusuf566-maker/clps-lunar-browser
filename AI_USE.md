# Use of artificial intelligence

This project was built with substantial help from an AI model. NASA Space Apps asks every team to
say where and how AI was used; this file is that statement for the code, the data and the
documents in this repository. Team: Yusuf Dündar and Serkan Dündar.

## Tool

**Anthropic's Claude**, used through the Claude app, throughout the project. No other AI tool was
used (no other chat assistant, code completion tool or image generator).

## Where and how

| Part | What Claude did | What the team did |
|---|---|---|
| Physics engine (`engine/`, Python) | Wrote most of the code: dynamics, transfer design, landing analysis, terrain, regolith temperature, forecast, communication maps | Chose the problem and the questions the tool must answer, set the requirements, checked the mathematics and the code, decided what to keep |
| Data scripts (`scripts/`) | Wrote them | Ran every one on our own computer with the real data (JPL DE440, LRO LOLA, LRO Diviner) and reviewed the output |
| Web interface (`web/src`, TypeScript / React) | Wrote most of it | Used it, asked for changes, checked the numbers it shows against the engine |
| Tests (`tests/`, `web/tests/`) | Wrote them, including the pass criteria we agreed before each check was run | Approved each criterion before the data was seen, ran the tests, kept failed checks as failed |
| Documentation (READMEs, `docs/`) | Drafted it, in English and Turkish | Read and corrected it |
| Presentation | Built the slide deck from the project's results | Reviewed it, filled in team and event details |
| Debugging | Diagnosed problems, e.g. a CI failure caused by how a test measured tiny angles | Reproduced and confirmed the fixes on our machine |

Both team members reviewed the results and checked the mathematics and the code. The forecast
registration (GitHub Release, archive.org copies, OpenTimestamps) was done by the team.

## How the AI's output was checked

No number in this project comes from the AI model itself. Every result is computed by the engine
or the web page from the data named above, and checked by tests that anyone can run:

- 106 engine tests (`python tests/run_all.py`) and the browser checks (`cd web && npm test`), which
  compare the browser's computations with the engine's;
- retrodiction of three flown missions (IM-1, IM-2, Blue Ghost 1) and comparisons with NASA Ames'
  Lunar Browser, NASA Goddard's polar illumination map, NASA's eclipse catalogue and LRO Diviner;
- pre-registered checks: the pass criterion is written into the code before the data is seen, and
  failed checks are reported as failed (see "Validation" and "At a glance" in the README).

AI-written code can be wrong in ways that look right; the tests above are how we looked for that.
Several of them failed and are reported as such.

## What is not AI-generated

- **Data:** every data file in `web/public/data` is computed by the engine's scripts from JPL and
  NASA data. None is produced by an AI model. The code that computes it is AI-assisted, as above.
- **Images:** the pictures on the website and in the presentation are rendered by our code from
  NASA data or are screenshots of the running website. There are no AI-generated images, so no
  "AI-generated" watermark applies. No NASA logo, flag or mission insignia is used.
- **The Griffin-1 forecast** (`forecast.json`) is the engine's output, registered before launch.

## Metadata

This statement is linked from both READMEs, and the package metadata says the code is
AI-assisted (`pyproject.toml`: description, keywords and the "AI use" link; `web/package.json`:
description).

## Text for the Space Apps submission form

> Yes. We used Anthropic's Claude (through the Claude app) throughout the project, and no other AI
> tool. Claude wrote most of the code (the Python physics engine, the data scripts, the TypeScript
> web interface and the tests), drafted the documentation and built the slide deck; it also
> diagnosed bugs. The team chose the problem and the questions the tool must answer, set the
> requirements, approved every pass criterion before the data was seen, ran all computations on our
> own computer with JPL DE440, LRO LOLA and LRO Diviner data, checked the mathematics and the code,
> reviewed the results and registered the Griffin-1 forecast. No number comes from the AI model
> itself: every result is computed by our engine and checked by published tests (engine tests,
> browser-versus-engine checks, retrodiction of IM-1, IM-2 and Blue Ghost 1, comparisons with NASA
> Ames, NASA Goddard and LRO Diviner); failed checks are reported as failed. The images are renders
> and screenshots of our website, not AI-generated. Details: AI_USE.md in our repository.
